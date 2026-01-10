"""
Distributed tracing setup for TDSC Backend.

This module configures structured logging and request/response tracing.
"""

import logging
import time
import uuid
from datetime import datetime
from typing import Callable
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import Response

# Configure structured logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)

logger = logging.getLogger(__name__)


class RequestIdMiddleware(BaseHTTPMiddleware):
    """Middleware to add request IDs to all requests for tracing."""
    
    async def dispatch(self, request: Request, call_next: Callable) -> Response:
        """Add request ID and trace request/response."""
        # Generate or get request ID
        request_id = request.headers.get('x-request-id', str(uuid.uuid4()))
        request.state.request_id = request_id
        
        # Log incoming request
        logger.info(f"[{request_id}] Incoming {request.method} {request.url.path}")
        
        # Record start time
        start_time = time.time()
        
        try:
            response = await call_next(request)
            
            # Calculate duration
            duration = time.time() - start_time
            
            # Log response
            logger.info(f"[{request_id}] Completed {request.method} {request.url.path} with status {response.status_code} (duration: {duration:.2f}s)")
            
            # Add request ID to response headers
            response.headers['x-request-id'] = request_id
            return response
            
        except Exception as e:
            duration = time.time() - start_time
            logger.error(f"[{request_id}] Error in {request.method} {request.url.path}: {str(e)} (duration: {duration:.2f}s)", exc_info=True)
            raise


class TraceLogger:
    """Helper class for logging operations with trace context."""
    
    def __init__(self, logger: logging.Logger):
        self.logger = logger
    
    def log_operation(self, operation: str, details: dict = None, request_id: str = None):
        """Log an operation with details."""
        message = f"[Operation] {operation}"
        if details:
            message += f" | {details}"
        
        extra = {'request_id': request_id} if request_id else {}
        self.logger.info(message, extra=extra)
    
    def log_database_operation(self, operation: str, collection: str, query_details: str = None, request_id: str = None):
        """Log a database operation."""
        message = f"[DB] {operation} on '{collection}'"
        if query_details:
            message += f" | {query_details}"
        
        extra = {'request_id': request_id} if request_id else {}
        self.logger.debug(message, extra=extra)
    
    def log_auth_event(self, event: str, user_identifier: str = None, request_id: str = None):
        """Log authentication-related events."""
        message = f"[Auth] {event}"
        if user_identifier:
            message += f" | User: {user_identifier}"
        
        extra = {'request_id': request_id} if request_id else {}
        self.logger.info(message, extra=extra)
    
    def log_error(self, error_message: str, exception: Exception = None, request_id: str = None):
        """Log errors with optional exception details."""
        extra = {'request_id': request_id} if request_id else {}
        self.logger.error(error_message, exc_info=exception, extra=extra)


# Global trace logger instance
trace_logger = TraceLogger(logger)


def get_trace_logger():
    """Get the global trace logger."""
    return trace_logger
