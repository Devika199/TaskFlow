from .models import Notification


def create_notification(recipient, actor, verb, task=None, notification_type=Notification.TYPE_SYSTEM):
    """
    Safely create an in-app notification.
    Does not create a notification if the actor is notifying themselves.
    """
    if not recipient or (actor and recipient.id == actor.id):
        return None

    return Notification.objects.create(
        recipient=recipient,
        actor=actor,
        verb=verb,
        task=task,
        notification_type=notification_type
    )
