from django.shortcuts import render, redirect
from django.contrib import messages
from django.db.models import Sum
from django.conf import settings
from django.utils.translation import gettext as _

from .models import Farmer, Village, District, Region, SeedType, Distribution, ContactMessage
from .forms import ContactForm
from .utils import send_email


def landing(request):
    if request.user.is_authenticated:
        return redirect('farmer_dashboard' if request.user.role == 'farmer' else 'dashboard')
    stats = {
        'farmers': Farmer.objects.count(),
        'villages': Village.objects.count(),
        'districts': District.objects.count(),
        'seed_types': SeedType.objects.count(),
        'distributed': Distribution.objects.aggregate(t=Sum('quantity_distributed'))['t'] or 0,
    }
    return render(request, 'marketing/landing.html', {'stats': stats})


def about(request):
    return render(request, 'marketing/about.html')


def how_it_works(request):
    return render(request, 'marketing/how_it_works.html')


def faq(request):
    return render(request, 'marketing/faq.html')


def contact(request):
    form = ContactForm(request.POST or None)
    if request.method == 'POST' and form.is_valid():
        msg = form.save()
        if settings.CONTACT_EMAIL:
            send_email(
                settings.CONTACT_EMAIL,
                f'Contact form: {msg.subject}',
                f'<p>From: {msg.name} ({msg.email})</p><p>{msg.message}</p>',
            )
        messages.success(request, _('Thank you - your message has been sent. We will respond soon.'))
        return redirect('contact')
    return render(request, 'marketing/contact.html', {'form': form})
