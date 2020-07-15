import os
from rest_framework import viewsets
from .mailingSystem import Mailer
import threading
from buggernaut.models import *
import requests
from django.http import Http404
from rest_framework.response import Response
from rest_framework import status
from rest_framework.decorators import action
from buggernaut.serializers import *
from django_filters import rest_framework as filters
from .permissions import *
from rest_framework.permissions import AllowAny, IsAuthenticated
from django.contrib.auth import login, logout
from buggernaut_backend.settings import base_configuration, BASE_DIR
# Create your views here.


class ProjectViewSet(viewsets.ModelViewSet):
    queryset = Project.objects.all()
    # serializer_class = self.get
    filter_backends = (filters.DjangoFilterBackend,)
    filterset_fields = ['deployed', 'slug']

    def perform_create(self, serializer):
        project = serializer.save()

        mailerInstance = Mailer()
        link = "http://localhost:3000/projects/"+project.slug
        x = threading.Thread(target=mailerInstance.newProjectUpdate, args=(project.title, link, project.members.all()))
        x.start()
        # mailerInstance.newProjectUpdate(project_name=project.title, project_link=link, team_members=project.members.all())

    def get_serializer_class(self):
        if self.action == "create" or self.action == "update" or self.action == "partial":
            return ProjectPostSerializer
        else:
            return ProjectGetSerializer

    @action(methods=['get', ], detail=False, url_path='verify', url_name='verify', permission_classes=[IsAuthenticated])
    def check_slug(self, request):
        slug = self.request.query_params.get('slug')
        # print(slug)
        try:
            Project.objects.get(slug=slug)
        except Project.DoesNotExist:
            return Response({"status": "Available"}, status=status.HTTP_202_ACCEPTED)

        return Response({"status": "Taken"}, status=status.HTTP_202_ACCEPTED)

    @action(methods=['get', ], detail=True, url_path='issues', url_name='issues', permission_classes=[IsAuthenticated])
    def get_issues(self, request, pk):

        try:
            issues_list = Issue.objects.filter(project=pk)
        except Issue.DoesNotExist:
            return Response({'Empty': 'No Issues for this project yet'}, status=status.HTTP_204_NO_CONTENT)

        ser = IssueGetSerializer(issues_list, many=True)
        # ser = UserSerializer(user)
        return Response(ser.data)

    @action(methods=['patch', ], detail=True, url_path='update-team', url_name='update-team', permission_classes=[IsAuthenticated])
    def update_team(self, request, pk):
        project = Project.objects.get(pk=pk)
        members_list = self.request.data["members"]
        # print("HEO")
        project.members.clear()
        for member in members_list:
            project.members.add(member)
        # print("HELLO")
        project.save()

        ser = ProjectGetSerializer(project)
        return Response(ser.data)

    @action(methods=['get', ], detail=True, url_path='deploy', url_name='deploy', permission_classes=[IsAuthenticated])
    def deploy_project(self, request, pk):
        project = Project.objects.get(pk=pk)

        if request.user.is_superuser or request.user in project.members:
            pass
        else:
            return Response({"Status":"Not authorized."} , status=status.HTTP_403_FORBIDDEN)

        if not Issue.objects.filter(project=project, resolved=False):
            project.deployed = True
            project.save()

            mailer = Mailer()
            x = threading.Thread(target=mailer.deployProject, args=(project.title, request.user.full_name, project.members.all()))
            x.start()
            # mailer.deployProject(project=project.title, deployed_by=request.user.full_name, team_members=project.members.all())

            return Response({'Status': 'Project successfully deployed'}, status=status.HTTP_202_ACCEPTED)
        else:
            return Response({'Status': 'All issues are not resolved for this project'})

    def destroy(self, request, *args, **kwargs):
        if request.user.is_authenticated and request.user.is_admin:
            pass
        else:
            return Response(status=status.HTTP_403_FORBIDDEN)

        try:
            instance = self.get_object()
            editor = instance.editorID
            images = Image.objects.filter(editorID=editor)

            for i in images:
                i.delete()
                url_tbd = BASE_DIR + i.url.url
                os.remove(url_tbd)

            self.perform_destroy(instance)
        except Http404:
            pass
        return Response(status=status.HTTP_204_NO_CONTENT)


class IssueViewSet(viewsets.ModelViewSet):
    queryset = Issue.objects.all()
    filter_backends = (filters.DjangoFilterBackend,)
    filterset_fields = ['reported_by', 'assigned_to']

    def perform_create(self, serializer):
        issue = serializer.save()
        # print(issue.reported_by)
        project = issue.project
        link = "http://localhost:3000/projects/" + project.slug
        mailer = Mailer()
        x = threading.Thread(target=mailer.newBugReported, args=(project.title, link, issue.reported_by.full_name, issue.subject, project.members.all()))
        x.start()
        # mailer.newBugReported( project_name=project.title, project_link=link, reported_by=issue.reported_by.full_name, issue_subject=issue.subject, team_members=project.members.all())

    def get_serializer_class(self):
        if self.action == "create":
            return IssuePostSerializer
        else:
            return IssueGetSerializer

    def destroy(self, request, *args, **kwargs):
        try:
            issue = self.get_object()
            project = issue.project
            link = "http://localhost:3000/projects/" + project.slug
            editor = issue.editorID
            images = Image.objects.filter(editorID=editor)

            for i in images:
                i.delete()
                url_tbd = BASE_DIR + i.url.url
                os.remove(url_tbd)

            mailer = Mailer()
            x = threading.Thread(target=mailer.bugStatusChanged, args=(project.title, link, issue.subject, "deleted", request.user.full_name, project.members.all()))
            x.start()
            # mailer.bugStatusChanged(project_name=project.title, project_link=link, issue_subject=issue.subject, action="deleted", doer=request.user.full_name, team_members=project.members.all())
            self.perform_destroy(issue)

        except Http404:
            pass

        return Response(status=status.HTTP_204_NO_CONTENT)

    @action(methods=['get', ], detail=True, url_path='resolve-or-reopen', url_name='resolve-or-reopen', permission_classes=[IsTeamMemberOrAdmin])
    def resolve_or_reopen(self, request, pk):
        user = self.request.user;
        issue = Issue.objects.get(pk=pk)
        if issue.resolved:
            issue.resolved = False
        else:
            issue.resolved = True

        issue.resolved_by = user;
        issue.save()

        project = issue.project
        link = "http://localhost:3000/projects/" + project.slug
        mailer = Mailer()

        if issue.resolved:
           x = threading.Thread(target=mailer.bugStatusChanged, args=(project.title, link, issue.subject, "resolved", request.user.full_name, project.members.all()))
           # mailer.bugStatusChanged(project_name=project.title, project_link=link, issue_subject=issue.subject, action="resolved", doer=request.user.full_name, team_members=project.members.all())
        else:
           x = threading.Thread(target=mailer.bugStatusChanged, args=(project.title, link, issue.subject, "reopened", request.user.full_name, project.members.all()))
           # mailer.bugStatusChanged(project_name=project.title, project_link=link, issue_subject=issue.subject, action="reopened", doer=request.user.full_name, team_members=project.members.all())
        x.start()
        ser = IssueGetSerializer(issue)
        return Response(ser.data, status=status.HTTP_200_OK)


    @action(methods=['get', ], detail=True, url_path='assign', url_name='assign', permission_classes=[IsTeamMemberOrAdmin])
    def assign_issue(self, request, pk):
        assign_to = self.request.query_params.get('assign_to')
        issue = Issue.objects.get(pk=pk)

        try:
            user = User.objects.get(pk=assign_to)
        except User.DoesNotExist:
            return Response({'Detail': 'User does not exist'}, status=status.HTTP_406_NOT_ACCEPTABLE)

        if user in issue.project.members.all():
            issue.assigned_to = user
            issue.save()

            assignment_link = "http://localhost:3000/mypage?show=my-assignments"
            project = issue.project
            assigned = issue.assigned_to

            # def bugAssigned(self, project_name, assignment_link, issue_subject, assigned_to_name, assigned_to_email):
            mailer = Mailer()
            x = threading.Thread(target=mailer.bugAssigned, args=(project.title, assignment_link, issue.subject, assigned.full_name, assigned.email))
            x.start()
            # mailer.bugAssigned(project_name=project.title, assignment_link=assignment_link, issue_subject=issue.subject, assigned_to_name=assigned.full_name, assigned_to_email=assigned.email)

            return Response({'Detail': 'Assignment Successful'}, status=status.HTTP_202_ACCEPTED)
        else:
            return Response({'Detail': 'User not a team member'}, status=status.HTTP_406_NOT_ACCEPTABLE)

    @action(methods=['get', ], detail=True, url_path='comments', url_name='comments', permission_classes=[IsAuthenticated])
    def get_comments(self, request, pk):

        try:
            comments_list = Comment.objects.filter(issue=pk)
        except Comment.DoesNotExist:
            return Response({'Empty': 'No comments for this issue'}, status=status.HTTP_204_NO_CONTENT)

        ser = CommentGetSerializer(comments_list, many=True)
        # ser = UserSerializer(user)
        return Response(ser.data)

# class UserViewSet(viewsets.ModelViewSet):
class UserViewSet(viewsets.ReadOnlyModelViewSet):
    queryset = User.objects.all()
    serializer_class = UserSerializer
    # permission_classes = [IsAdmin, ]

    @action(methods=['post', 'options', ], detail=False, url_name="onlogin", url_path="onlogin",
            permission_classes=[AllowAny])
    def on_login(self, request):

        ode = self.request.data
        code = ode["code"]

        # GET AUTHORIZATION CODE
        url = "https://internet.channeli.in/open_auth/token/"
        data = {
            'client_id': base_configuration["secrets"]["clientID"],
            'client_secret': base_configuration["secrets"]["clientSecret"],
            'grant_type': 'authorization_code',
            'redirect_url': 'http://localhost:3000/onlogin',
            'code': code
        }
        user_data = requests.post(url=url, data=data).json()

        if(user_data == None):
            return Response({"status": "invalid token"})
        ac_tok = user_data['access_token']
        # GET ACCESS TOKEN
        headers = {
            'Authorization': 'Bearer ' + ac_tok,
        }
        user_data = requests.get(url="https://internet.channeli.in/open_auth/get_user_data/", headers=headers).json()
        # print(user_data.text)
        # return Response(user_data)
        # CHECK IF USER EXISTS

        try:
            user = User.objects.get(enrolment_number=user_data["student"]["enrolmentNumber"])
        except User.DoesNotExist:
            # CHECK IMG MEMBER OR NOT
            in_img = False
            for role in user_data["person"]["roles"]:
                if role["role"] == "Maintainer":
                    in_img = True
                    break

            if in_img:
                # CREATE USER
                enrolNum = user_data["student"]["enrolmentNumber"]
                email = user_data["contactInformation"]["instituteWebmailAddress"]

                name = (user_data["person"]["fullName"]).split()
                firstName = name[0]
                fullName = user_data["person"]["fullName"]

                if user_data["person"]["displayPicture"] is None:
                    picture = "https://ui-avatars.com/api/?name=" + name[0] + "+" + name[
                        1] + "&background=DCD6F7&color=412234&size=512"
                else:
                    picture = "https://internet.channeli.in" + user_data["person"]["displayPicture"]

                is_admin = False
                if user_data["student"]["currentYear"] >= 3:
                    is_admin = True

                newUser = User(enrolment_number=enrolNum, username=enrolNum, email=email, first_name=firstName, full_name=fullName,
                               is_superuser=is_admin, is_staff=is_admin, display_picture=picture)
                newUser.save()
                login(request=request, user=newUser)
                # ser = UserSerializer(newUser)
                return Response({"status": "user created"}, status=status.HTTP_202_ACCEPTED)
            else:
                # SORRY YOU CAN'T USE THIS
                return Response({"status": "user not in IMG"})

        if user.banned:
            return Response({"status": "user banned"})

        login(request=request, user=user)
        # request.session["user"] = "dingo"
        return Response({"status": "user exists"})

    @action(methods=['post', 'options', ], detail=False, url_name="login", url_path="login",
            permission_classes=[AllowAny])
    def pre_login(self, request):
        # print({"hello":"o"})
        data = self.request.data
        token = data["access_token"]

        try:
            user = User.objects.get(access_token=token)
        except User.DoesNotExist:
            return Response({"status": "user does not exist in database"})

        # LOGIN
        login(request=request, user=user)
        # request.session["user"] = user
        return Response({"status": "user found"}, status=status.HTTP_202_ACCEPTED)

    @action(methods=['get', 'options', ], detail=False, url_name="logout_user", url_path="logout_user", permission_classes=[IsAuthenticated])
    def logout_user(self, request):
        logout(request)
        return Response({"status":"logged_out"})

    @action(methods=['get', 'options', ], detail=False, url_name="test", url_path="test", permission_classes=[AllowAny])
    def test(self, request):
        if request.user.is_authenticated:
            if request.user.banned:
                logout(request)
                return Response({"enrolment_number":"user banned"})
            ser = UserSerializer(request.user)
            return Response(ser.data, status=status.HTTP_202_ACCEPTED)
        else:
            return Response({"enrolment_number": "Not authenticated"})

    @action(methods=['get', 'options', ], detail=False, url_name="stats", url_path="stats", permission_classes=[AllowAny])
    def get_stats(self, request):
        if request.user.is_authenticated:
            if request.user.banned:
                logout(request)
                return Response({"enrolment_number":"user banned"})
            reported = Issue.objects.filter(reported_by=request.user).count()
            resolved = Issue.objects.filter(resolved_by=request.user).count()
            stats = {"resolved": resolved, "reported":reported}
            ser = UserSerializer(request.user)
            return Response({**ser.data, **stats}, status=status.HTTP_202_ACCEPTED)
        else:
            return Response({"enrolment_number": "Not authenticated"})

    @action(methods=['get', 'options', ], detail=True, url_name="toggleStatus", url_path="toggleStatus", permission_classes=[IsAuthenticated])
    def toggleStatus(self, request, pk):
        if request.user.is_superuser:
            user = User.objects.get(pk=pk)
            if user == request.user:
                return Response({"status": "You cannot change your own status!"})

            if user.is_superuser:
                user.is_superuser = False
                user.is_staff = False
            else:
                user.is_superuser = True
                user.is_staff = True

            user.save()

            mailer = Mailer()

            if user.is_superuser:
                x = threading.Thread(target=mailer.statusUpdate, args=(user.email, user.full_name, "promote", request.user.full_name))
                # mailer.statusUpdate(user_email=user.email, user_name=user.full_name, change="promote", changer=request.user.full_name)
            else:
                x = threading.Thread(target=mailer.statusUpdate, args=(user.email, user.full_name, "demote", request.user.full_name))
                # mailer.statusUpdate(user_email=user.email, user_name=user.full_name, change="demote", changer=request.user.full_name)
            x.start()
            return Response({"status": "Role updated"}, status=status.HTTP_200_OK)
        else:
            return Response({"status": "You're not an admin"}, status=status.HTTP_403_FORBIDDEN)

    @action(methods=['get', 'options', ], detail=True, url_name="toggleBan", url_path="toggleBan", permission_classes=[IsAuthenticated])
    def toggleBan(self, request, pk):
        if request.user.is_superuser:
            user = User.objects.get(pk=pk)
            if user == request.user:
                return Response({"status": "You cannot change your own status!"})

            if user.banned:
                user.banned = False
            else:
                user.banned = True
                user.is_superuser = False
                user.is_staff = False

            user.save()

            mailer = Mailer()

            if user.banned:
                x = threading.Thread(target=mailer.banOrAdmitUser, args=(user.email, user.full_name, "banned", request.user.full_name))
                # mailer.banOrAdmitUser(user_email=user.email, user_name=user.full_name, change="banned",
                #                     changer=request.user.full_name)
            else:
                x = threading.Thread(target=mailer.banOrAdmitUser, args=(user.email, user.full_name, "admit", request.user.full_name))
                # mailer.banOrAdmitUser(user_email=user.email, user_name=user.full_name, change="admit",
                #                     changer=request.user.full_name)
            x.start()
            return Response({"status": "Status updated"}, status=status.HTTP_200_OK)
        else:
            return Response({"status": "You're not an admin"}, status=status.HTTP_403_FORBIDDEN)


class TagViewSet(viewsets.ModelViewSet):
    queryset = Tag.objects.all()
    serializer_class = TagSerializer

class ImageViewSet(viewsets.ModelViewSet):
    queryset = Image.objects.all()
    serializer_class = ImageSerializer

    @action(methods=['POST'], detail=False, url_path='deleteRem', url_name='deleteRem')
    def delete_remaining_images(self, request):
        if request.user.is_authenticated:
            editor_id = request.POST.get('editorID')
            urls = request.POST.get('urls')

            images = Image.objects.filter(editorID=editor_id)

            for i in images:
                print(i)
                print("editor_id: ",i.editorID)
                print("url: ",i.url)
                if i.url.url not in urls:
                    print("deleting")
                    url_tbd = BASE_DIR + i.url.url
                    print(url_tbd)
                    if os.path.exists(url_tbd):
                        i.delete()
                        os.remove(url_tbd)
                        print("deleted")
                    else:
                        print("wrong url")

            return Response({"status": "successful"})
        else:
            return Response({"Detail": "Not authenticated"})


class CommentViewSet(viewsets.ModelViewSet):
    queryset = Comment.objects.all()


    def get_serializer_class(self):
        if self.action == "create":
            return CommentPostSerializer
        else:
            return CommentGetSerializer
