"""
Expo Push Notification Sender

Sends push notifications via Expo's push API.
No Firebase needed — Expo handles iOS APNs and Android FCM transparently.

API docs: https://docs.expo.dev/push-notifications/sending-notifications/
"""

import httpx
import logging
from typing import List, Optional, Dict, Any

logger = logging.getLogger(__name__)

EXPO_PUSH_URL = "https://exp.host/--/api/v2/push/send"


async def send_push_notification(
    token: str,
    title: str,
    body: str,
    data: Optional[Dict[str, Any]] = None,
    badge: Optional[int] = None,
    sound: str = "default",
    channel_id: str = "default",
) -> bool:
    """
    Send a single push notification via Expo Push API.
    
    Args:
        token: Expo push token (ExponentPushToken[xxx])
        title: Notification title
        body: Notification body text
        data: Extra data payload (visible to app, not to user)
        badge: iOS badge count
        sound: Notification sound ('default' or None)
        channel_id: Android notification channel
    
    Returns:
        True if sent successfully, False otherwise
    """
    message = {
        "to": token,
        "title": title,
        "body": body,
        "sound": sound,
        "channelId": channel_id,
    }

    if data:
        message["data"] = data
    if badge is not None:
        message["badge"] = badge

    try:
        async with httpx.AsyncClient() as client:
            response = await client.post(
                EXPO_PUSH_URL,
                json=message,
                headers={
                    "Accept": "application/json",
                    "Content-Type": "application/json",
                },
                timeout=10.0,
            )

            if response.status_code == 200:
                result = response.json()
                ticket = result.get("data", {})
                
                if ticket.get("status") == "error":
                    error_msg = ticket.get("message", "Unknown error")
                    error_type = ticket.get("details", {}).get("error", "")
                    logger.error(f"Expo push error: {error_msg} ({error_type})")
                    
                    # Token is invalid — caller should deactivate it
                    if error_type == "DeviceNotRegistered":
                        return False
                    return False
                
                logger.info(f"Push sent successfully to {token[:30]}...")
                return True
            else:
                logger.error(f"Expo push HTTP error: {response.status_code} - {response.text}")
                return False

    except Exception as e:
        logger.error(f"Expo push exception: {e}")
        return False


async def send_push_notifications_bulk(
    messages: List[Dict[str, Any]]
) -> List[Dict[str, Any]]:
    """
    Send multiple push notifications in a single request.
    
    Expo supports up to 100 notifications per request.
    
    Args:
        messages: List of message dicts with 'to', 'title', 'body', 'data', etc.
    
    Returns:
        List of results with token and success status.
    """
    if not messages:
        return []

    results = []

    # Expo allows max 100 per batch
    for i in range(0, len(messages), 100):
        batch = messages[i:i + 100]

        # Ensure all messages have defaults
        for msg in batch:
            msg.setdefault("sound", "default")
            msg.setdefault("channelId", "default")

        try:
            async with httpx.AsyncClient() as client:
                response = await client.post(
                    EXPO_PUSH_URL,
                    json=batch,
                    headers={
                        "Accept": "application/json",
                        "Content-Type": "application/json",
                    },
                    timeout=15.0,
                )

                if response.status_code == 200:
                    result = response.json()
                    tickets = result.get("data", [])
                    
                    for j, ticket in enumerate(tickets):
                        token = batch[j].get("to", "unknown")
                        success = ticket.get("status") == "ok"
                        invalid = ticket.get("details", {}).get("error") == "DeviceNotRegistered"
                        
                        results.append({
                            "token": token,
                            "success": success,
                            "invalid_token": invalid,
                        })
                else:
                    logger.error(f"Expo bulk push HTTP error: {response.status_code}")
                    for msg in batch:
                        results.append({
                            "token": msg.get("to", "unknown"),
                            "success": False,
                            "invalid_token": False,
                        })

        except Exception as e:
            logger.error(f"Expo bulk push exception: {e}")
            for msg in batch:
                results.append({
                    "token": msg.get("to", "unknown"),
                    "success": False,
                    "invalid_token": False,
                })

    return results
