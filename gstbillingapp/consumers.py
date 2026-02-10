# Django Channels Consumer for Real-time Notifications
import json
from channels.generic.websocket import AsyncWebsocketConsumer
from channels.db import database_sync_to_async
from django.contrib.auth.models import User


class NotificationConsumer(AsyncWebsocketConsumer):
    """
    WebSocket consumer for real-time notifications.
    Each user gets their own notification channel.
    """
    
    async def connect(self):
        """Handle WebSocket connection"""
        # Get user from scope (set by AuthMiddlewareStack)
        self.user = self.scope['user']
        
        # Only allow authenticated users
        if not self.user.is_authenticated:
            await self.close()
            return
        
        # Create unique channel for this user
        self.room_name = f"notifications_{self.user.id}"
        self.room_group_name = f"notifications_user_{self.user.id}"
        
        # Join user's notification group
        await self.channel_layer.group_add(
            self.room_group_name,
            self.channel_name
        )
        
        # Accept WebSocket connection
        await self.accept()
        
        # Send current unread count on connection
        unread_count = await self.get_unread_count()
        await self.send(text_data=json.dumps({
            'type': 'unread_count',
            'count': unread_count
        }))
    
    async def disconnect(self, close_code):
        """Handle WebSocket disconnection"""
        if hasattr(self, 'room_group_name'):
            # Leave notification group
            await self.channel_layer.group_discard(
                self.room_group_name,
                self.channel_name
            )
    
    async def receive(self, text_data):
        """
        Receive message from WebSocket
        (Client can request current count)
        """
        try:
            data = json.loads(text_data)
            message_type = data.get('type', '')
            
            if message_type == 'get_count':
                # Client requesting unread count
                unread_count = await self.get_unread_count()
                await self.send(text_data=json.dumps({
                    'type': 'unread_count',
                    'count': unread_count
                }))
            
            elif message_type == 'ping':
                # Keep-alive ping
                await self.send(text_data=json.dumps({
                    'type': 'pong'
                }))
        
        except json.JSONDecodeError:
            pass
    
    async def notification_message(self, event):
        """
        Receive notification from channel layer and send to WebSocket
        """
        # Send notification to WebSocket
        await self.send(text_data=json.dumps({
            'type': 'notification',
            'notification': event['notification']
        }))
    
    async def count_update(self, event):
        """
        Receive count update from channel layer and send to WebSocket
        """
        await self.send(text_data=json.dumps({
            'type': 'unread_count',
            'count': event['count']
        }))
    
    @database_sync_to_async
    def get_unread_count(self):
        """Get unread notification count for user"""
        from gstbillingapp.models import Notification
        return Notification.objects.filter(
            user=self.user,
            is_read=False,
            is_deleted=False
        ).count()


# Utility function to send notification via WebSocket
async def send_notification_to_user(user_id, notification_data):
    """
    Send notification to user's WebSocket channel
    
    Usage:
        from asgiref.sync import async_to_sync
        from channels.layers import get_channel_layer
        
        channel_layer = get_channel_layer()
        async_to_sync(channel_layer.group_send)(
            f"notifications_user_{user.id}",
            {
                'type': 'notification_message',
                'notification': {
                    'id': notification.id,
                    'title': notification.title,
                    'message': notification.message,
                    'notification_type': notification.notification_type,
                    'link_url': notification.link_url,
                }
            }
        )
    """
    from channels.layers import get_channel_layer
    
    channel_layer = get_channel_layer()
    await channel_layer.group_send(
        f"notifications_user_{user_id}",
        {
            'type': 'notification_message',
            'notification': notification_data
        }
    )


async def send_count_update_to_user(user_id, count):
    """Send updated unread count to user's WebSocket"""
    from channels.layers import get_channel_layer
    
    channel_layer = get_channel_layer()
    await channel_layer.group_send(
        f"notifications_user_{user_id}",
        {
            'type': 'count_update',
            'count': count
        }
    )
