from django.urls import path

from . import views

app_name = "ai_assistant"

urlpatterns = [
    path("", views.chat_page, name="chat"),
    path("message/", views.chat_message, name="message"),
]
