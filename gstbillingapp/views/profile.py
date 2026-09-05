# Django imports
from django.contrib.auth.decorators import login_required
from django.shortcuts import render, redirect, get_object_or_404

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
def user_profile_edit(request):
    context = {}
    user_profile = get_object_or_404(UserProfile, user=request.user)
    context['user_profile_form'] = UserProfileForm(instance=user_profile, user=request.user)

    if request.method == "POST":
        user_profile_form = UserProfileForm(request.POST, instance=user_profile, user=request.user)
        user_profile_form.save()
        return redirect('user_profile')
    return render(request, 'profile/user_profile_edit.html', context)