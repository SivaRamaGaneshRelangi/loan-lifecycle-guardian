from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session


from ..database import get_db
from ..models import User
from ..schemas import ChatIn
from ..security import get_current_user
from ..services.agent import chat

router = APIRouter(prefix="/api/agent", tags=["agent"])


@router.post("/chat")
def agent_chat(d: ChatIn, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    return chat(db, user, d.message, d.history)
