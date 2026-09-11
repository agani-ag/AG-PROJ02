"""/syncup/callback — where SyncUp posts an admin's Approve / Reject answer.

SyncUp signs the raw body with GSTSync's signing secret (Console → Settings) in
X-SyncUp-Signature; anything unsigned or wrongly signed is refused. Repeats of the same
request_id are ignored (syncup_messages.apply_answer), so a replay changes nothing.
"""
import json

from django.http import JsonResponse
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_POST

from .. import syncup_messages
from ..models import SyncUpSettings


@csrf_exempt
@require_POST
def syncup_callback(request):
    secret = SyncUpSettings.load().signing_secret
    if not secret:
        return JsonResponse({"ok": False}, status=404)
    if not syncup_messages.verify_signature(request.body,
                                            request.headers.get("X-SyncUp-Signature"), secret):
        return JsonResponse({"ok": False, "message": "Bad signature"}, status=403)
    try:
        data = json.loads(request.body or b"{}")
    except ValueError:
        return JsonResponse({"ok": False, "message": "Not JSON"}, status=400)
    if data.get("type") != "approve" or data.get("status") != "completed":
        return JsonResponse({"ok": True, "result": "ignored"})
    result = syncup_messages.apply_answer(str(data.get("request_id") or ""),
                                          str(data.get("value") or ""))
    return JsonResponse({"ok": True, "result": result})
