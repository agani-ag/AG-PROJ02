"""Keeping rows and people in step — the whole of the old mapping work, done by itself.

A customer row or an employee belongs to whoever holds its mobile number. So whenever a row is
saved, its number may have changed hands: it is re-pointed at the right person, that person's
app login is opened if they don't have one yet, and the person it left is brought back in step
with what they can still see (usually nothing, so their login switches off).

Nothing here can block or slow a business: the SyncUp side runs after the save commits, with a
short timeout, and records a failure for /cron/syncup rather than raising.
"""
import logging

from django.db import transaction
from django.db.models.signals import post_delete, post_save, pre_delete
from django.dispatch import receiver

from . import appusers, identity
from .models import AppUser, Customer, Employee, EmployeePosting

log = logging.getLogger(__name__)


def _later(fn, *args):
    def run():
        try:
            fn(*args)
        except Exception:  # noqa: BLE001 — never break a business action over app access
            log.exception("identity upkeep (%s) failed", fn.__name__)
    transaction.on_commit(run)


def _sync(previous_id, person_id):
    """The part that talks to SyncUp — after the save commits, never in its way."""
    if previous_id and previous_id != person_id:
        left = AppUser.objects.filter(pk=previous_id).first()
        if left is not None and not identity.detach_unused(left):
            appusers.refresh_login(left)
    if person_id:
        person = AppUser.objects.filter(pk=person_id).first()
        if person is not None:
            # New number, new person: open the app for them straight away. Their password is
            # their number, so there is nothing to hand over.
            appusers.ensure_login(person)
            appusers.refresh_login(person)


def _settle(row):
    """Point the row at whoever holds its number NOW — a DB write, so it happens at once and
    the rest of the request sees it — then sync the logins once the save commits."""
    previous_id = row.app_user_id
    person = identity.attach(row)
    _later(_sync, previous_id, person.id if person else None)
    return person


@receiver(post_save, sender=Customer, dispatch_uid="identity_customer_saved")
def _customer_saved(sender, instance, raw=False, **kwargs):
    if not raw:
        _settle(instance)


@receiver(post_save, sender=Employee, dispatch_uid="identity_employee_saved")
def _employee_saved(sender, instance, raw=False, **kwargs):
    if not raw:
        _settle(instance)


@receiver(post_delete, sender=Customer, dispatch_uid="identity_customer_deleted")
@receiver(post_delete, sender=Employee, dispatch_uid="identity_employee_deleted")
def _row_deleted(sender, instance, **kwargs):
    person_id = instance.app_user_id
    if not person_id:
        return

    def settle():
        person = AppUser.objects.filter(pk=person_id).first()
        if person is not None and not identity.detach_unused(person):
            appusers.refresh_login(person)
    _later(settle)


@receiver(pre_delete, sender=Employee, dispatch_uid="identity_employee_deleting")
def _employee_deleting(sender, instance, **kwargs):
    """Their postings go with them, so their staff access may end here."""
    _row_deleted(sender, instance)


@receiver(post_save, sender=EmployeePosting, dispatch_uid="identity_posting_saved")
@receiver(post_delete, sender=EmployeePosting, dispatch_uid="identity_posting_deleted")
def _posting_changed(sender, instance, **kwargs):
    """A posting switched on or off changes whether the staff app has anything to open."""
    person_id = getattr(instance.employee, "app_user_id", None)
    if person_id:
        _later(appusers.refresh_people, [person_id])
