"""Customer Surveys — the business side (desktop).

A business builds a Survey (many questions), activates it, and every customer answers it
(in the SyncUp mobile app, or via an employee on their behalf). Results are shown both as
per-question aggregates and as a by-customer table you can filter to a target list.
"""
import csv
import json

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.paginator import Paginator
from django.db.models import Count, Q
from django.http import HttpResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.views.decorators.http import require_POST

from ..models import Customer, Survey, SurveyAnswer, SurveyQuestion, SurveyResponse

_VALID_TYPES = dict(SurveyQuestion.TYPE_CHOICES)
_STATUSES = {Survey.DRAFT, Survey.ACTIVE, Survey.CLOSED}


# --------------------------------------------------------------------------- #
# Shared answer save/prefill — used by the mobile customer & employee screens
# --------------------------------------------------------------------------- #
def save_survey_response(survey, customer, source, posting, raw):
    """Create or update `customer`'s answer-set for `survey`.

    `raw` maps question id (str) -> raw value: bool for yes/no, an option id for single,
    a list of option ids for multi, a string for text. Returns (ok, error_message).
    """
    questions = list(survey.questions.all())
    cleaned = {}
    for q in questions:
        rv = raw.get(str(q.id))
        val = None
        if q.type == SurveyQuestion.BOOL:
            if isinstance(rv, bool):
                val = {"bool": rv}
        elif q.type == SurveyQuestion.SINGLE:
            ids = {o["id"] for o in q.options}
            if rv in ids:
                val = {"option": rv}
        elif q.type == SurveyQuestion.MULTI:
            ids = {o["id"] for o in q.options}
            sel = [x for x in rv if x in ids] if isinstance(rv, list) else []
            if sel:
                val = {"options": sel}
        else:  # text_short / text_long
            text = rv.strip() if isinstance(rv, str) else ""
            if text:
                maxlen = (q.config or {}).get("maxlen") or 2000
                val = {"text": text[:maxlen]}
        if q.required and val is None:
            return False, "Please answer: %s" % q.text
        if val is not None:
            cleaned[q.id] = val

    resp, _ = SurveyResponse.objects.get_or_create(
        survey=survey, customer=customer, defaults={"source": source})
    resp.source = source
    resp.answered_by_employee = posting
    resp.save()
    resp.answers.all().delete()
    SurveyAnswer.objects.bulk_create(
        [SurveyAnswer(response=resp, question_id=qid, value=val) for qid, val in cleaned.items()])
    return True, None


def response_raw_values(survey, customer):
    """Existing answers as {question_id: raw value}, for prefilling the answer form."""
    resp = survey.responses.filter(customer=customer).first()
    out = {}
    if not resp:
        return out
    for a in resp.answers.select_related("question"):
        q, v = a.question, (a.value or {})
        if q.type == SurveyQuestion.BOOL:
            out[q.id] = v.get("bool")
        elif q.type == SurveyQuestion.SINGLE:
            out[q.id] = v.get("option")
        elif q.type == SurveyQuestion.MULTI:
            out[q.id] = v.get("options") or []
        else:
            out[q.id] = v.get("text") or ""
    return out


# --------------------------------------------------------------------------- #
# List
# --------------------------------------------------------------------------- #
def _filtered_surveys(request):
    qs = (Survey.objects.filter(user=request.user)
          .annotate(n_questions=Count("questions", distinct=True),
                    n_responses=Count("responses", distinct=True))
          .order_by("-created_at", "-id"))
    q = (request.GET.get("q") or "").strip()
    if q:
        qs = qs.filter(title__icontains=q)
    status = (request.GET.get("status") or "").strip()
    if status in _STATUSES:
        qs = qs.filter(status=status)
    return qs, {"q": q, "status": status}


@login_required
def surveys(request):
    qs, fctx = _filtered_surveys(request)
    paginator = Paginator(qs, 25)
    page_obj = paginator.get_page(request.GET.get("page"))
    params = request.GET.copy()
    params.pop("page", None)
    base = Survey.objects.filter(user=request.user)
    context = dict(fctx)
    context.update({
        "surveys": page_obj, "page_obj": page_obj, "total_count": paginator.count,
        "total_customers": Customer.objects.filter(user=request.user).count(),
        "querystring": params.urlencode(),
        "count_all": base.count(),
        "count_active": base.filter(status=Survey.ACTIVE).count(),
        "count_draft": base.filter(status=Survey.DRAFT).count(),
        "count_closed": base.filter(status=Survey.CLOSED).count(),
    })
    return render(request, "surveys/surveys.html", context)


# --------------------------------------------------------------------------- #
# Builder (create / edit)
# --------------------------------------------------------------------------- #
def _questions_to_json(survey):
    """Serialize a survey's questions to the shape the builder JS expects."""
    return json.dumps([
        {"text": q.text, "type": q.type, "required": q.required,
         "options": [o["label"] for o in q.options]}
        for q in survey.questions.all()
    ])


def _parse_questions(raw):
    """Validate the builder's posted questions_json. Returns (clean_list, errors)."""
    try:
        items = json.loads(raw or "[]")
        if not isinstance(items, list):
            items = []
    except (json.JSONDecodeError, TypeError):
        items = []
    clean, errors = [], []
    for item in items:
        if not isinstance(item, dict):
            continue
        text = (item.get("text") or "").strip()
        qtype = item.get("type")
        if not text or qtype not in _VALID_TYPES:
            continue
        config = {}
        if qtype in SurveyQuestion.CHOICE_TYPES:
            opts = [str(o).strip() for o in (item.get("options") or []) if str(o).strip()]
            if len(opts) < 2:
                errors.append('“%s” needs at least two options.' % text[:40])
            config["options"] = [{"id": "o%d" % (i + 1), "label": lab}
                                 for i, lab in enumerate(opts)]
        elif qtype in SurveyQuestion.TEXT_TYPES:
            config["maxlen"] = 2000 if qtype == SurveyQuestion.TEXT_LONG else 200
        clean.append({"text": text[:400], "type": qtype,
                      "required": bool(item.get("required")), "config": config})
    if not clean:
        errors.append("Add at least one question.")
    return clean, errors


def _save_survey(request, survey, locked):
    title = (request.POST.get("title") or "").strip()
    description = (request.POST.get("description") or "").strip()
    raw_questions = request.POST.get("questions_json") or "[]"

    errors = []
    if not title:
        errors.append("A survey title is required.")
    clean, qerrors = _parse_questions(raw_questions)
    # Question errors only matter when we're actually (re)writing questions.
    if not locked:
        errors.extend(qerrors)

    if errors:
        return render(request, "surveys/survey_form.html", {
            "survey": survey, "mode": "edit" if survey else "new",
            "questions_json": raw_questions, "locked": locked,
            "entered": {"title": title, "description": description},
            "errors": errors,
        }, status=400)

    if survey is None:
        survey = Survey.objects.create(user=request.user, title=title, description=description)
    else:
        survey.title = title
        survey.description = description
        survey.save(update_fields=["title", "description", "updated_at"])

    if not locked:
        survey.questions.all().delete()
        for i, q in enumerate(clean):
            SurveyQuestion.objects.create(
                survey=survey, order=i, text=q["text"], type=q["type"],
                required=q["required"], config=q["config"])

    messages.success(request, "Survey saved.")
    return redirect("survey_edit", pk=survey.id)


@login_required
def survey_new(request):
    if request.method == "POST":
        return _save_survey(request, survey=None, locked=False)
    return render(request, "surveys/survey_form.html",
                  {"survey": None, "mode": "new", "questions_json": "[]", "locked": False})


@login_required
def survey_edit(request, pk):
    survey = get_object_or_404(Survey, pk=pk, user=request.user)
    locked = survey.responses.exists()  # structure freezes once anyone has answered
    if request.method == "POST":
        return _save_survey(request, survey=survey, locked=locked)
    return render(request, "surveys/survey_form.html", {
        "survey": survey, "mode": "edit", "questions_json": _questions_to_json(survey),
        "locked": locked,
    })


# --------------------------------------------------------------------------- #
# Lifecycle
# --------------------------------------------------------------------------- #
@login_required
@require_POST
def survey_activate(request, pk):
    survey = get_object_or_404(Survey, pk=pk, user=request.user)
    if not survey.questions.exists():
        messages.error(request, "Add at least one question before activating.")
    else:
        survey.status = Survey.ACTIVE
        survey.save(update_fields=["status", "updated_at"])
        messages.success(request, "Survey is now active — customers can answer it.")
    return redirect("surveys")


@login_required
@require_POST
def survey_close(request, pk):
    survey = get_object_or_404(Survey, pk=pk, user=request.user)
    survey.status = Survey.CLOSED
    survey.save(update_fields=["status", "updated_at"])
    messages.success(request, "Survey closed.")
    return redirect("surveys")


@login_required
@require_POST
def survey_duplicate(request, pk):
    survey = get_object_or_404(Survey, pk=pk, user=request.user)
    clone = Survey.objects.create(
        user=request.user, title=(survey.title + " (copy)")[:200],
        description=survey.description, status=Survey.DRAFT)
    for q in survey.questions.all():
        SurveyQuestion.objects.create(
            survey=clone, order=q.order, text=q.text, type=q.type,
            required=q.required, config=q.config)
    messages.success(request, "Survey duplicated as a draft.")
    return redirect("survey_edit", pk=clone.id)


@login_required
@require_POST
def survey_delete(request, pk):
    survey = get_object_or_404(Survey, pk=pk, user=request.user)
    survey.delete()
    messages.success(request, "Survey deleted.")
    return redirect("surveys")


# --------------------------------------------------------------------------- #
# Results (aggregate + by-customer)
# --------------------------------------------------------------------------- #
def _answer_map(survey):
    """(response_id, question_id) -> value, in one query."""
    out = {}
    for a in SurveyAnswer.objects.filter(response__survey=survey).values(
            "response_id", "question_id", "value"):
        out[(a["response_id"], a["question_id"])] = a["value"] or {}
    return out


def _render_value(question, value):
    """Human-readable cell text for a question's answer."""
    value = value or {}
    if question.type == SurveyQuestion.BOOL:
        b = value.get("bool")
        return "Yes" if b is True else ("No" if b is False else "")
    if question.type == SurveyQuestion.SINGLE:
        labels = {o["id"]: o["label"] for o in question.options}
        return labels.get(value.get("option"), "")
    if question.type == SurveyQuestion.MULTI:
        labels = {o["id"]: o["label"] for o in question.options}
        return ", ".join(labels.get(oid, "") for oid in (value.get("options") or []) if labels.get(oid))
    return (value.get("text") or "").strip()


def _aggregate(questions, responses, amap):
    result = []
    n = len(responses)
    for q in questions:
        item = {"q": q}
        if q.type == SurveyQuestion.BOOL:
            yes = sum(1 for r in responses if amap.get((r.id, q.id), {}).get("bool") is True)
            no = sum(1 for r in responses if amap.get((r.id, q.id), {}).get("bool") is False)
            tot = yes + no
            item["bool"] = {
                "yes": yes, "no": no, "total": tot,
                "yes_pct": round(yes / tot * 100) if tot else 0,
                "no_pct": round(no / tot * 100) if tot else 0,
            }
        elif q.type in SurveyQuestion.CHOICE_TYPES:
            counts = {o["id"]: 0 for o in q.options}
            for r in responses:
                v = amap.get((r.id, q.id), {})
                sel = v.get("options") if q.type == SurveyQuestion.MULTI else (
                    [v.get("option")] if v.get("option") else [])
                for oid in (sel or []):
                    if oid in counts:
                        counts[oid] += 1
            item["choices"] = [
                {"label": o["label"], "count": counts.get(o["id"], 0),
                 "pct": round(counts.get(o["id"], 0) / n * 100) if n else 0}
                for o in q.options]
        else:
            item["texts"] = [
                {"text": t, "customer": r.customer.customer_name}
                for r in responses
                for t in [(amap.get((r.id, q.id), {}).get("text") or "").strip()] if t]
        result.append(item)
    return result


def _match_filter(question, value, fv):
    """Does this answer match the by-customer filter value?"""
    value = value or {}
    if question.type == SurveyQuestion.BOOL:
        return (fv == "yes" and value.get("bool") is True) or (fv == "no" and value.get("bool") is False)
    if question.type == SurveyQuestion.SINGLE:
        return value.get("option") == fv
    if question.type == SurveyQuestion.MULTI:
        return fv in (value.get("options") or [])
    return fv.lower() in (value.get("text") or "").lower()


@login_required
def survey_results(request, pk):
    survey = get_object_or_404(Survey, pk=pk, user=request.user)
    questions = list(survey.questions.all())
    responses = list(survey.responses.select_related("customer", "answered_by_employee__employee"))
    amap = _answer_map(survey)

    # Optional by-customer filter (?fq=<question id>&fv=<yes|no|option id|text>)
    fq = (request.GET.get("fq") or "").strip()
    fv = (request.GET.get("fv") or "").strip()
    fq_question = next((q for q in questions if str(q.id) == fq), None)
    if fq_question and fv:
        responses = [r for r in responses
                     if _match_filter(fq_question, amap.get((r.id, fq_question.id)), fv)]

    aggregate = _aggregate(questions, responses, amap)
    rows = [{
        "customer": r.customer,
        "source": r.get_source_display(),
        "by": (r.answered_by_employee.employee.name if r.answered_by_employee else ""),
        "submitted": r.updated_at,
        "cells": [_render_value(q, amap.get((r.id, q.id))) for q in questions],
    } for r in responses]

    total_customers = Customer.objects.filter(user=survey.user).count()
    answered = survey.responses.count()
    return render(request, "surveys/survey_results.html", {
        "survey": survey, "questions": questions, "aggregate": aggregate, "rows": rows,
        "answered": answered, "total_customers": total_customers,
        "coverage_pct": round(answered / total_customers * 100) if total_customers else 0,
        "fq": fq, "fv": fv,
        "querystring": request.GET.urlencode(),
    })


@login_required
def survey_export(request, pk):
    survey = get_object_or_404(Survey, pk=pk, user=request.user)
    questions = list(survey.questions.all())
    responses = list(survey.responses.select_related("customer", "answered_by_employee__employee"))
    amap = _answer_map(survey)

    response = HttpResponse(content_type="text/csv")
    response["Content-Disposition"] = 'attachment; filename="survey-%d.csv"' % survey.id
    writer = csv.writer(response)
    writer.writerow(["Customer", "Phone"] + [q.text for q in questions] + ["Answered by", "Submitted"])
    for r in responses:
        writer.writerow(
            [r.customer.customer_name, r.customer.customer_phone or ""]
            + [_render_value(q, amap.get((r.id, q.id))) for q in questions]
            + [r.get_source_display() + (
                " (%s)" % r.answered_by_employee.employee.name if r.answered_by_employee else ""),
               r.updated_at.strftime("%d %b %Y %H:%M")]
        )
    return response


# --------------------------------------------------------------------------- #
# Desktop: owner records a customer's answers (e.g. over a phone call)
# --------------------------------------------------------------------------- #
def _raw_from_post(questions, post):
    raw = {}
    for q in questions:
        key = "q%d" % q.id
        if q.type == SurveyQuestion.BOOL:
            v = post.get(key)
            if v == "true":
                raw[str(q.id)] = True
            elif v == "false":
                raw[str(q.id)] = False
        elif q.type == SurveyQuestion.SINGLE:
            v = post.get(key)
            if v:
                raw[str(q.id)] = v
        elif q.type == SurveyQuestion.MULTI:
            vals = post.getlist(key)
            if vals:
                raw[str(q.id)] = vals
        else:
            t = (post.get(key) or "").strip()
            if t:
                raw[str(q.id)] = t
    return raw


@login_required
def survey_respond(request, pk):
    survey = get_object_or_404(Survey, pk=pk, user=request.user)
    customers = Customer.objects.filter(user=request.user).order_by("customer_name")

    if request.method == "POST":
        cust = get_object_or_404(Customer, pk=request.POST.get("customer") or 0, user=request.user)
        if survey.status != Survey.ACTIVE:
            messages.error(request, "Activate the survey before recording responses.")
            return redirect("survey_respond", pk=survey.id)
        raw = _raw_from_post(list(survey.questions.all()), request.POST)
        ok, err = save_survey_response(survey, cust, SurveyResponse.OWNER, None, raw)
        messages.success(request, "Response saved for %s." % cust.customer_name) if ok \
            else messages.error(request, err)
        return redirect(reverse("survey_respond", args=[survey.id]) + "?customer=%d" % cust.id)

    selected = None
    sid = request.GET.get("customer")
    if sid and sid.isdigit():
        selected = customers.filter(id=int(sid)).first()

    questions = list(survey.questions.all())
    prefill = response_raw_values(survey, selected) if selected else {}
    for q in questions:
        v = prefill.get(q.id)
        if q.type == SurveyQuestion.BOOL:
            q.pf = "true" if v is True else ("false" if v is False else "")
        elif q.type == SurveyQuestion.MULTI:
            q.pf_set = set(v or [])
        else:
            q.pf = v if v else ""

    return render(request, "surveys/survey_respond.html", {
        "survey": survey, "customers": customers, "selected": selected,
        "questions": questions, "answered": survey.responses.filter(customer=selected).exists() if selected else False,
    })
