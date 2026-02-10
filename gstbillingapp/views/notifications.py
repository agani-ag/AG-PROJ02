# Django imports
from django.shortcuts import render, get_object_or_404
from django.http import JsonResponse
from django.contrib.auth.decorators import login_required
from django.views.decorators.http import require_http_methods
from django.core.paginator import Paginator
from datetime import datetime

# Models
from ..models import Notification

# Utils
from ..utils import get_unread_notification_count, mark_all_notifications_read


# ================= Notification Views ===========================

@login_required
def notifications_page(request):
    """
    Main notifications page - displays all notifications for the user
    """
    context = {}
    
    # Get filter parameters
    filter_type = request.GET.get('type', 'all')
    filter_status = request.GET.get('status', 'all')
    
    # Base query
    notifications_query = Notification.objects.filter(
        user=request.user,
        is_deleted=False
    )
    
    # Apply filters
    if filter_type != 'all':
        notifications_query = notifications_query.filter(notification_type=filter_type)
    
    if filter_status == 'unread':
        notifications_query = notifications_query.filter(is_read=False)
    elif filter_status == 'read':
        notifications_query = notifications_query.filter(is_read=True)
    
    # Pagination
    paginator = Paginator(notifications_query, 20)  # 20 notifications per page
    page_number = request.GET.get('page', 1)
    notifications = paginator.get_page(page_number)
    
    context['notifications'] = notifications
    context['unread_count'] = get_unread_notification_count(request.user)
    context['filter_type'] = filter_type
    context['filter_status'] = filter_status
    context['notification_types'] = Notification.NOTIFICATION_TYPES
    
    return render(request, 'notifications/notifications.html', context)


@login_required
@require_http_methods(["GET"])
def notifications_api(request):
    """
    API endpoint to get notifications (for auto-refresh)
    Returns JSON with notifications data
    """
    # Get parameters
    limit = int(request.GET.get('limit', 10))
    offset = int(request.GET.get('offset', 0))
    unread_only = request.GET.get('unread_only', 'false').lower() == 'true'
    
    # Base query
    notifications_query = Notification.objects.filter(
        user=request.user,
        is_deleted=False
    )
    
    if unread_only:
        notifications_query = notifications_query.filter(is_read=False)
    
    # Get notifications with limit and offset
    notifications = notifications_query[offset:offset + limit]
    
    # Prepare response data
    notifications_data = []
    for notification in notifications:
        notifications_data.append({
            'id': notification.id,
            'type': notification.notification_type,
            'title': notification.title,
            'message': notification.message,
            'link_url': notification.link_url,
            'link_text': notification.link_text,
            'is_read': notification.is_read,
            'created_at': notification.created_at.strftime('%Y-%m-%d %H:%M:%S'),
            'icon_class': notification.get_icon_class(),
            'badge_class': notification.get_badge_class(),
        })
    
    response_data = {
        'success': True,
        'notifications': notifications_data,
        'unread_count': get_unread_notification_count(request.user),
        'total_count': notifications_query.count(),
        'has_more': notifications_query.count() > (offset + limit)
    }
    
    return JsonResponse(response_data)


@login_required
@require_http_methods(["POST"])
def notification_mark_read(request, notification_id):
    """
    Mark a single notification as read
    """
    notification = get_object_or_404(
        Notification, 
        id=notification_id, 
        user=request.user,
        is_deleted=False
    )
    
    notification.mark_as_read()
    
    # Send WebSocket update
    try:
        from asgiref.sync import async_to_sync
        from channels.layers import get_channel_layer
        
        channel_layer = get_channel_layer()
        if channel_layer:
            unread_count = get_unread_notification_count(request.user)
            async_to_sync(channel_layer.group_send)(
                f"notifications_user_{request.user.id}",
                {
                    'type': 'count_update',
                    'count': unread_count
                }
            )
    except Exception:
        pass
    
    return JsonResponse({
        'success': True,
        'message': 'Notification marked as read',
        'unread_count': get_unread_notification_count(request.user)
    })


@login_required
@require_http_methods(["POST"])
def notification_mark_all_read(request):
    """
    Mark all notifications as read for the current user
    """
    mark_all_notifications_read(request.user)
    
    # Send WebSocket update
    try:
        from asgiref.sync import async_to_sync
        from channels.layers import get_channel_layer
        
        channel_layer = get_channel_layer()
        if channel_layer:
            async_to_sync(channel_layer.group_send)(
                f"notifications_user_{request.user.id}",
                {
                    'type': 'count_update',
                    'count': 0
                }
            )
    except Exception:
        pass
    
    return JsonResponse({
        'success': True,
        'message': 'All notifications marked as read',
        'unread_count': 0
    })


@login_required
@require_http_methods(["POST"])
def notification_delete(request, notification_id):
    """
    Soft delete a notification
    """
    notification = get_object_or_404(
        Notification, 
        id=notification_id, 
        user=request.user
    )
    
    notification.is_deleted = True
    notification.save()
    
    # Send WebSocket update
    try:
        from asgiref.sync import async_to_sync
        from channels.layers import get_channel_layer
        
        channel_layer = get_channel_layer()
        if channel_layer:
            unread_count = get_unread_notification_count(request.user)
            async_to_sync(channel_layer.group_send)(
                f"notifications_user_{request.user.id}",
                {
                    'type': 'count_update',
                    'count': unread_count
                }
            )
    except Exception:
        pass
    
    return JsonResponse({
        'success': True,
        'message': 'Notification deleted',
        'unread_count': get_unread_notification_count(request.user)
    })


@login_required
@require_http_methods(["POST"])
def notification_delete_all_read(request):
    """
    Delete all read notifications for the current user
    """
    deleted_count = Notification.objects.filter(
        user=request.user,
        is_read=True,
        is_deleted=False
    ).update(is_deleted=True)
    
    return JsonResponse({
        'success': True,
        'message': f'{deleted_count} notifications deleted',
        'deleted_count': deleted_count
    })


@login_required
@require_http_methods(["GET"])
def notification_count_api(request):
    """
    API endpoint to get unread notification count only
    (Lightweight endpoint for navbar badge)
    """
    return JsonResponse({
        'success': True,
        'unread_count': get_unread_notification_count(request.user)
    })
