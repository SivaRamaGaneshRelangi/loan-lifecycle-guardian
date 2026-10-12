from ..models import AuditLog, Notification, User


def notify(db, user_id, title, message, kind="INFO"):
    db.add(Notification(user_id=user_id, title=title[:160], message=message, kind=kind))


def notify_role(db, role, title, message, kind="INFO"):
    for u in db.query(User).filter(User.role == role, User.is_active == True).all():  # noqa: E712
        notify(db, u.id, title, message, kind)


def audit(db, actor_id, action, entity, entity_id=None, detail=""):
    db.add(AuditLog(actor_id=actor_id, action=action, entity=entity,
                    entity_id=entity_id, detail=detail[:500]))
