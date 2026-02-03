import json
from django.http import JsonResponse
from django.shortcuts import render
from django.views.decorators.csrf import csrf_exempt
from django.contrib.auth.decorators import login_required
from django.utils.dateparse import parse_datetime
from ..models import LiveLocation, GeoFence, GeoFenceEvent
from ..utils import distance_meters

# ---------------- DASHBOARDS ----------------
@login_required
def customer_dashboard(request):
    return render(request, "location/customer.html")

@login_required
def employee_dashboard(request):
    return render(request, "location/employee.html")

@login_required
def admin_dashboard(request):
    return render(request, "location/admin.html")

# ---------------- PUSH LOCATION ----------------
@csrf_exempt
@login_required
def push_location(request):
    data = json.loads(request.body)

    user_type = "employee" if request.user.is_staff else "customer"

    loc = LiveLocation.objects.create(
        user_id=data.get("user_id", "unknown"),
        user_type=user_type,
        room=data.get("room", "default"),
        lat=data["lat"],
        lng=data["lng"],
        accuracy=data.get("accuracy", "gps")
    )

    # GEOFENCE CHECK
    for fence in GeoFence.objects.filter(active=True):
        dist = distance_meters(
            loc.lat, loc.lng,
            fence.center_lat, fence.center_lng
        )

        inside = dist <= fence.radius_meters
        last = GeoFenceEvent.objects.filter(
            user_id=loc.user_id, fence=fence
        ).order_by("-created_at").first()

        if inside and (not last or last.event_type == "exit"):
            GeoFenceEvent.objects.create(
                user_id=loc.user_id,
                user_type=user_type,
                fence=fence,
                event_type="enter"
            )

        if not inside and last and last.event_type == "enter":
            GeoFenceEvent.objects.create(
                user_id=loc.user_id,
                user_type=user_type,
                fence=fence,
                event_type="exit"
            )

    return JsonResponse({"status": "ok"})

# ---------------- POLLING ----------------
@login_required
def poll_locations(request):
    since = request.GET.get("since")
    user_type = request.GET.get("user_type")

    qs = LiveLocation.objects.all()
    if user_type:
        qs = qs.filter(user_type=user_type)
    if since:
        dt = parse_datetime(since)
        if dt:
            qs = qs.filter(created_at__gt=dt)

    return JsonResponse([
        {
            "user": l.user_id,
            "lat": l.lat,
            "lng": l.lng,
            "time": l.created_at.isoformat()
        } for l in qs
    ], safe=False)

@login_required
def route_history(request):
    user = request.GET.get("user")
    qs = LiveLocation.objects.filter(user_id=user).order_by("created_at")
    return JsonResponse([[l.lat, l.lng] for l in qs], safe=False)

@login_required
def geofence_events(request):
    since = request.GET.get("since")
    qs = GeoFenceEvent.objects.all()
    if since:
        dt = parse_datetime(since)
        if dt:
            qs = qs.filter(created_at__gt=dt)

    return JsonResponse([
        {
            "user": e.user_id,
            "event": e.event_type,
            "fence": e.fence.name,
            "time": e.created_at.isoformat()
        } for e in qs
    ], safe=False)
