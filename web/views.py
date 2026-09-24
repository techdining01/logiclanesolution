import json
import logging

import requests
from django.conf import settings
from django.core.mail import send_mail
from django.http import JsonResponse
from django.shortcuts import render
from django.views.decorators.http import require_POST

logger = logging.getLogger(__name__)


def home(request):
    return render(request, 'logiclane-solutions.html')


@require_POST
def book_session(request):
    """
    Handles a "Book a session" submission from the site:
    1. Emails the booking details to LogicLane.
    2. Asks Payvessel to start a checkout for the session fee and returns
       the checkout URL for the browser to redirect to.
    """
    try:
        data = json.loads(request.body or '{}')
    except (json.JSONDecodeError, TypeError):
        return JsonResponse({'error': 'Invalid request body.'}, status=400)

    required_fields = ['service', 'tier', 'amount', 'name', 'email', 'phone', 'date', 'time']
    missing = [f for f in required_fields if not data.get(f)]
    if missing:
        return JsonResponse({'error': f'Missing fields: {", ".join(missing)}'}, status=400)

    _email_booking(data)

    checkout_url = _create_payvessel_transaction(data)
    if not checkout_url:
        return JsonResponse(
            {'error': 'Could not start the Payvessel checkout. Please try again shortly.'},
            status=502,
        )

    return JsonResponse({'payvessel_checkout_url': checkout_url})


def _email_booking(data):
    """Send the booking to LogicLane's inbox. Never blocks the request on failure."""
    subject = f"Session booking: {data['service']} ({data['tier']})"
    message = (
        f"Service: {data['service']}\n"
        f"Plan: {data['tier']} (\u20a6{int(data['amount']):,})\n"
        f"Name: {data['name']}\n"
        f"Email: {data['email']}\n"
        f"Phone: {data['phone']}\n"
        f"Preferred date: {data['date']}\n"
        f"Preferred time: {data['time']}\n"
        f"Notes: {data.get('notes', '')}"
    )
    try:
        send_mail(
            subject=subject,
            message=message,
            from_email=getattr(settings, 'DEFAULT_FROM_EMAIL', None),
            recipient_list=['logiclanesolutions@gmail.com'],
            fail_silently=False,
        )
    except Exception:
        # Don't let an email/SMTP hiccup stop the booking or payment flow —
        # just log it so it can be checked later.
        logger.exception('Failed to send booking notification email.')


def _create_payvessel_transaction(data):
    """
    Calls Payvessel's transaction-initialize endpoint and returns the
    checkout URL to redirect the customer to.

    Requires these in settings.py (get them from your Payvessel merchant
    dashboard — never expose them in the template/JS):
        PAYVESSEL_API_KEY
        PAYVESSEL_BUSINESS_ID
        PAYVESSEL_API_URL   (defaults to https://api.payvessel.com)

    NOTE: the endpoint path and payload keys below are a best-effort
    scaffold based on Payvessel's published API shape, not a confirmed
    live contract. Check the current API reference in your Payvessel
    merchant dashboard and adjust `endpoint` / `payload` / the response
    parsing at the bottom of this function to match exactly before going
    live.
    """
    api_key = getattr(settings, 'PAYVESSEL_API_KEY', None)
    business_id = getattr(settings, 'PAYVESSEL_BUSINESS_ID', None)
    api_url = getattr(settings, 'PAYVESSEL_API_URL', 'https://api.payvessel.com')

    if not api_key or not business_id:
        logger.error('Payvessel is not configured (missing API key/business id).')
        return None

    endpoint = f'{api_url.rstrip("/")}/transactions/initialize'
    payload = {
        'businessId': business_id,
        'amount': data['amount'],
        'email': data['email'],
        'name': data['name'],
        'phoneNumber': data['phone'],
        'currency': 'NGN',
        'metadata': {
            'service': data['service'],
            'tier': data['tier'],
            'date': data['date'],
            'time': data['time'],
            'notes': data.get('notes', ''),
        },
    }
    headers = {
        'Authorization': f'Bearer {api_key}',
        'Content-Type': 'application/json',
    }

    try:
        response = requests.post(endpoint, json=payload, headers=headers, timeout=10)
        response.raise_for_status()
        result = response.json()
    except requests.RequestException:
        logger.exception('Payvessel transaction initialize request failed.')
        return None

    return (
        result.get('data', {}).get('checkoutUrl')
        or result.get('checkoutUrl')
        or result.get('data', {}).get('authorization_url')
    )
