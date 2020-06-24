from django.urls import re_path

from . import consumers

websocket_urlpatterns = [
    # re_path(r'ws/issue/(?P<issue_id>\w+)/comments/$', consumers.CommentConsumer),
    re_path(r'ws/projects/(?P<project_id>\w+)/comments/$', consumers.CommentConsumer),
]