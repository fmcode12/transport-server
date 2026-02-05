import os
from fastapi import HTTPException, status, Security
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from dotenv import load_dotenv
import os
from slowapi import Limiter
from slowapi.util import get_remote_address

limiter = Limiter(key_func=get_remote_address)

load_dotenv()
security = HTTPBearer()

def validate_admin(auth: HTTPAuthorizationCredentials = Security(security)):
    secret = os.getenv("ADMIN_SECRET_TOKEN")
    if auth.credentials != secret:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="You are not authorized to perform this action",
        )
    return True


