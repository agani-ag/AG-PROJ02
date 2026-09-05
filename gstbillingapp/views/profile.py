# Django imports
from django.contrib.auth import update_session_auth_hash
from django.contrib.auth.decorators import login_required
from django.http import JsonResponse
from django.shortcuts import render, redirect, get_object_or_404
from django.views.decorators.http import require_POST

# Models
from ..models import UserProfile

# Forms
from ..forms import UserProfileForm


# ================= User Management =============================
@login_required
def user_profile(request):
    from .presence import device_info, _active_count
    context = {}
    user_profile = get_object_or_404(UserProfile, user=request.user)
    context['user_profile'] = user_profile
    context['devices'] = device_info(request.user)
    context['devices_online'] = _active_count(request.user)
    context['this_device_token'] = request.session.get('device_token', '')
    return render(request, 'profile/user_profile.html', context)


@login_required
@require_POST
def change_password(request):
    """Set a new password for the signed-in user. By request, the current password is
    NOT required (the user is already authenticated); we only take the new password and
    a confirmation. update_session_auth_hash keeps THIS session logged in after the
    change instead of Django's default sign-out."""
    new = request.POST.get("new_password") or ""
    confirm = request.POST.get("confirm_password") or ""
    if len(new) < 4:
        return JsonResponse({"error": "Password must be at least 4 characters."}, status=400)
    if new != confirm:
        return JsonResponse({"error": "The two passwords do not match."}, status=400)
    request.user.set_password(new)
    request.user.save()
    update_session_auth_hash(request, request.user)
    return JsonResponse({"message": "Password changed successfully."})


@login_required
def user_profile_edit(request):
    context = {}
    user_profile = get_object_or_404(UserProfile, user=request.user)
    context['user_profile_form'] = UserProfileForm(instance=user_profile, user=request.user)

    if request.method == "POST":
        user_profile_form = UserProfileForm(request.POST, instance=user_profile, user=request.user)
        user_profile_form.save()
        return redirect('user_profile')
    return render(request, 'profile/user_profile_edit.html', context)