"""
Blog engagement routes (votes, comments) using MongoDB for TDSC Backend.
"""

from fastapi import APIRouter, HTTPException, Depends, status, Request
from typing import Optional, List
from datetime import datetime
from pydantic import BaseModel, Field
from bson import ObjectId

from database import Database, get_db
from routes.auth import get_current_user, require_auth
from models.db_models import Vote, Comment
from tracing import get_trace_logger

router = APIRouter(prefix="/posts", tags=["Engagement"])
trace_logger = get_trace_logger()


# Pydantic schemas
class VoteCreate(BaseModel):
    vote_type: str  # "up" or "down"


class VoteResponse(BaseModel):
    upvotes: int
    downvotes: int
    user_vote: Optional[str] = None


class CommentCreate(BaseModel):
    text: str = Field(..., min_length=1, max_length=2000)


class CommentResponse(BaseModel):
    id: str
    username: str
    text: str
    created_at: datetime
    is_own: bool = False


# ============ VOTES ============

@router.get("/{slug}/votes", response_model=VoteResponse)
def get_votes(
    slug: str,
    db: Database = Depends(get_db),
    current_user: Optional[dict] = Depends(get_current_user)
):
    """Get vote counts for a post"""
    votes = db.get_collection('votes')
    
    # Count upvotes
    upvotes = votes.count_documents({"post_slug": slug, "vote_type": "up"})
    
    # Count downvotes
    downvotes = votes.count_documents({"post_slug": slug, "vote_type": "down"})
    
    # Get current user's vote if authenticated
    user_vote = None
    if current_user:
        user_vote_doc = votes.find_one({
            "post_slug": slug,
            "user_id": ObjectId(current_user['id'])
        })
        if user_vote_doc:
            user_vote = user_vote_doc['vote_type']
    
    return VoteResponse(upvotes=upvotes, downvotes=downvotes, user_vote=user_vote)


@router.post("/{slug}/votes", response_model=VoteResponse)
def submit_vote(
    slug: str,
    vote_data: VoteCreate,
    db: Database = Depends(get_db),
    current_user: dict = Depends(require_auth),
    request: Request = None
):
    """Submit or update a vote for a post"""
    request_id = getattr(request.state, 'request_id', None) if request else None
    trace_logger.log_operation("Vote Submission", {"post_slug": slug, "vote_type": vote_data.vote_type, "user_id": current_user['id']}, request_id)
    
    votes = db.get_collection('votes')
    vote_type = vote_data.vote_type
    
    if vote_type not in ('up', 'down'):
        trace_logger.log_operation("Vote Submission Failed", {"reason": "Invalid vote type"}, request_id)
        raise HTTPException(status_code=400, detail="Vote type must be 'up' or 'down'")
    
    user_id = ObjectId(current_user['id'])
    
    # Check if user already voted
    trace_logger.log_database_operation("Query", "votes", f"post_slug={slug}, user_id={current_user['id']}", request_id)
    existing_vote = votes.find_one({
        "post_slug": slug,
        "user_id": user_id
    })
    
    if existing_vote:
        if existing_vote['vote_type'] == vote_type:
            # Same vote type - remove the vote (toggle off)
            trace_logger.log_database_operation("Delete", "votes", f"id={existing_vote['_id']}", request_id)
            votes.delete_one({"_id": existing_vote['_id']})
        else:
            # Different vote type - update the vote
            trace_logger.log_database_operation("Update", "votes", f"id={existing_vote['_id']}, new_type={vote_type}", request_id)
            votes.update_one(
                {"_id": existing_vote['_id']},
                {"$set": {"vote_type": vote_type, "updated_at": datetime.utcnow()}}
            )
    else:
        # New vote
        new_vote = Vote.create_doc(current_user['id'], slug, vote_type)
        trace_logger.log_database_operation("Insert", "votes", f"post_slug={slug}, vote_type={vote_type}", request_id)
        votes.insert_one(new_vote)
    
    trace_logger.log_operation("Vote Submission Successful", {"post_slug": slug}, request_id)
    
    # Return updated counts
    return get_votes(slug, db, current_user)


# ============ COMMENTS ============

@router.get("/{slug}/comments", response_model=List[CommentResponse])
def get_comments(
    slug: str,
    db: Database = Depends(get_db),
    current_user: Optional[dict] = Depends(get_current_user)
):
    """Get all comments for a post"""
    comments = db.get_collection('comments')
    users = db.get_collection('users')
    
    comment_docs = list(comments.find({"post_slug": slug}).sort("created_at", -1))
    
    result = []
    for comment in comment_docs:
        user = users.find_one({"_id": comment['user_id']})
        result.append(CommentResponse(
            id=str(comment['_id']),
            username=user['username'] if user else "Unknown",
            text=comment['text'],
            created_at=comment['created_at'],
            is_own=current_user is not None and comment['user_id'] == ObjectId(current_user['id'])
        ))
    
    return result


@router.post("/{slug}/comments", response_model=CommentResponse)
def add_comment(
    slug: str,
    comment_data: CommentCreate,
    db: Database = Depends(get_db),
    current_user: dict = Depends(require_auth),
    request: Request = None
):
    """Add a comment to a post"""
    request_id = getattr(request.state, 'request_id', None) if request else None
    trace_logger.log_operation("Comment Creation", {"post_slug": slug, "user_id": current_user['id']}, request_id)
    
    comments = db.get_collection('comments')
    
    new_comment = Comment.create_doc(current_user['id'], slug, comment_data.text)
    trace_logger.log_database_operation("Insert", "comments", f"post_slug={slug}", request_id)
    result = comments.insert_one(new_comment)
    
    created_comment = comments.find_one({"_id": result.inserted_id})
    
    trace_logger.log_operation("Comment Creation Successful", {"post_slug": slug, "comment_id": str(result.inserted_id)}, request_id)
    
    return CommentResponse(
        id=str(created_comment['_id']),
        username=current_user['username'],
        text=comment_data.text,
        created_at=created_comment['created_at'],
        is_own=True
    )


@router.delete("/{slug}/comments/{comment_id}")
def delete_comment(
    slug: str,
    comment_id: str,
    db: Database = Depends(get_db),
    current_user: dict = Depends(require_auth),
    request: Request = None
):
    """Delete a comment (only the author can delete)"""
    request_id = getattr(request.state, 'request_id', None) if request else None
    trace_logger.log_operation("Comment Deletion", {"comment_id": comment_id, "user_id": current_user['id']}, request_id)
    
    comments = db.get_collection('comments')
    
    try:
        trace_logger.log_database_operation("Query", "comments", f"id={comment_id}", request_id)
        comment = comments.find_one({"_id": ObjectId(comment_id)})
    except:
        trace_logger.log_operation("Comment Deletion Failed", {"reason": "Invalid comment ID"}, request_id)
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Comment not found")
    
    if not comment:
        trace_logger.log_operation("Comment Deletion Failed", {"reason": "Comment not found"}, request_id)
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Comment not found")
    
    if comment['user_id'] != ObjectId(current_user['id']):
        trace_logger.log_operation("Comment Deletion Failed", {"reason": "Unauthorized - not author"}, request_id)
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="You can only delete your own comments")
    
    trace_logger.log_database_operation("Delete", "comments", f"id={comment_id}", request_id)
    comments.delete_one({"_id": ObjectId(comment_id)})
    
    trace_logger.log_operation("Comment Deletion Successful", {"comment_id": comment_id}, request_id)
    
    return {"message": "Comment deleted"}
