# encoding: utf-8
import unittest.mock as mock
import pytest
from bs4 import BeautifulSoup

import ckan.tests.factories as factories
import ckan.tests.helpers as helpers
from ckan import model
from ckan.lib.helpers import url_for
from ckan.lib.mailer import create_reset_key, MailerException


def _clear_activities():
    model.Session.query(model.ActivityDetail).delete()
    model.Session.query(model.Activity).delete()
    model.Session.flush()


@pytest.fixture
def user():
    user = factories.User(password="correct123")
    user_token = factories.APIToken(user=user["name"])
    user["token"] = user_token["token"]
    return user


@pytest.fixture
def sysadmin():
    user = factories.Sysadmin(password="correct123")
    user_token = factories.APIToken(user=user["name"])
    user["token"] = user_token["token"]
    return user


@pytest.mark.usefixtures("clean_db", "with_request_context")
class TestUser(object):
    def test_register_a_user(self, app):
        url = url_for("user.register")
        stub = factories.User.stub()
        response = app.post(
            url=url,
            data={
                "save": "",
                "name": stub.name,
                "fullname": "New User",
                "email": stub.email,
                "password1": "TestPassword1",
                "password2": "TestPassword1",
            },
        )

        assert 200 == response.status_code

        user = helpers.call_action("user_show", id=stub.name)
        assert user["name"] == stub.name
        assert user["fullname"] == "New User"
        assert not (user["sysadmin"])

    def test_register_user_bad_password(self, app):
        stub = factories.User.stub()
        response = app.post(
            url_for("user.register"),
            data={
                "save": "",
                "name": stub.name,
                "fullname": "New User",
                "email": stub.email,
                "password1": "TestPassword1",
                "password2": "",
            },
        )
        assert "The passwords you entered do not match" in response

    @pytest.mark.usefixtures("with_request_context")
    def test_create_user_as_sysadmin(self, app):
        admin_pass = "RandomPassword123"
        sysadmin = factories.Sysadmin(password=admin_pass)
        sysadmin_token = factories.APIToken(user=sysadmin["name"])

        env = {"Authorization": sysadmin_token["token"]}
        stub = factories.User.stub()
        response = app.post(
            url_for("user.register"),
            data={
                "name": stub.name,
                "fullname": "Newest User",
                "email": stub.email,
                "password1": "NewPassword1",
                "password2": "NewPassword1",
                "save": "",
            },
            extra_environ=env,
            follow_redirects=False,
        )
        assert "/user/activity" in response.headers["location"]

    def test_registered_user_login(self, app):
        """
        Registered user can submit valid login details at /user/login and
        be returned to appropriate place.
        """
        # make a user
        password = "RandomPassword123"
        user = factories.User(password=password)

        # get the form
        response = app.post(
            url_for("user.login"),
            data={
                "login": user["name"],
                "password": password
            },
        )
        # the response is the user dashboard, right?
        assert '<a href="/dashboard/">Dashboard</a>' in response
        assert (
            '<span class="username">{0}</span>'.format(user["fullname"])
            in response
        )

        # and we're definitely not back on the login page.
        assert '<h1 class="page-heading">Login</h1>' not in response

    def test_registered_user_login_bad_password(self, app):
        """
        Registered user is redirected to appropriate place if they submit
        invalid login details at /user/login.
        """

        # make a user
        user = factories.User()

        # get the form
        response = app.post(
            url_for("user.login"),
            data={"login": user["name"], "password": "BadPass1", "save": ""},
        )

        # the response is the login page again
        assert '<h1 class="page-heading">Login</h1>' in response
        assert "Login failed. Bad username or password." in response
        # and we're definitely not on the dashboard.
        assert '<a href="/dashboard">Dashboard</a>' not in response
        assert (
            '<span class="username">{0}</span>'.format(user["fullname"])
            not in response
        )

    def test_user_logout_url_redirect(self, app, user):
        """_logout url redirects to logged out page.
        """
        env = {"Authorization": user["token"]}
        logout_url = url_for("user.logout")
        final_response = app.get(logout_url, extra_environ=env)

        assert "You are now logged out." in final_response

    @pytest.mark.ckan_config("ckan.root_path", "/my/prefix")
    def test_non_root_user_logout_url_redirect(self, app, user):
        """
        _logout url redirects to logged out page with `ckan.root_path`
        prefixed.
        """
        env = {"Authorization": user["token"]}
        logout_url = url_for("user.logout")
        # Remove the prefix otherwise the test app won't find the correct route
        logout_url = logout_url.replace("/my/prefix", "")
        logout_response = app.get(logout_url, extra_environ=env, follow_redirects=False)
        assert logout_response.status_code == 302
        assert "/my/prefix/user/logged_out_redirect" in logout_response.headers["location"]

    def test_not_logged_in_dashboard(self, app):
        for route in ["index", "organizations", "datasets", "groups"]:
            response = app.get(
                url=url_for(u"dashboard.{}".format(route)),
                follow_redirects=False,
            )
            assert response.status_code == 302
            assert "user/login" in response.headers["location"]

    def test_own_datasets_show_up_on_user_dashboard(self, app, user):
        env = {"Authorization": user["token"]}
        dataset_title = "My very own dataset"
        factories.Dataset(
            user=user, name="my-own-dataset", title=dataset_title
        )

        response = app.get(url=url_for("dashboard.datasets"), extra_environ=env)

        assert dataset_title in response

    def test_other_datasets_dont_show_up_on_user_dashboard(self, app, user):
        env = {"Authorization": user["token"]}
        user1 = factories.User()
        dataset_title = "Someone else's dataset"
        factories.Dataset(
            user=user1, title=dataset_title
        )

        response = app.get(url=url_for("dashboard.datasets"), extra_environ=env)

        assert not (dataset_title in response)

    def test_user_edit_no_user(self, app):

        response = app.get(url_for("user.edit", id=None), status=400)
        assert "No user specified" in response

    def test_user_edit_unknown_user(self, app):
        """Attempt to read edit user for an unknown user redirects to login
        page."""

        res = app.get(
            url_for(
                "user.edit",
                id=factories.User.stub().name),
                status=302,
                follow_redirects=False
        )
        # Anonymous users are redirected to login page
        assert "user/login.html?next=%2Fuser%2Fedit%2F" in res

    def test_user_edit_not_logged_in(self, app):
        """Attempt to read edit user for an existing, not-logged in user
        redirects to login page."""

        user = factories.User()
        username = user["name"]
        url = url_for("user.edit", id=username)
        res = app.get(url, status=302, follow_redirects=False)
        # Anonymous users are redirected to login page
        assert "user/login.html?next=%2Fuser%2Fedit%2F" in res

    def test_edit_user(self, app, user):
        env = {"Authorization": user["token"]}
        app.post(
            url=url_for("user.edit"),
            data={
                "save": "",
                "name": user["name"],
                "fullname": "new full name",
                "email": 'user@ckan.org',
                "about": "new about",
                "activity_streams_email_notifications": True,
                "old_password": "correct123",
                "password1": "NewPass1",
                "password2": "NewPass1",
            },
            extra_environ=env
        )

        user = model.Session.query(model.User).get(user["id"])

        assert user.fullname == "new full name"
        assert user.email == 'user@ckan.org'
        assert user.about == "new about"
        assert user.activity_streams_email_notifications

    def test_edit_user_as_wrong_user(self, app, user):
        user_one = factories.User(password="TestPassword1")
        env = {"Authorization": user["token"]}
        app.get(url_for("user.edit", id=user_one["name"]), extra_environ=env, status=403)

    def test_email_change_without_password(self, app, user):
        env = {"Authorization": user["token"]}
        response = app.post(
            url=url_for("user.edit"),
            data={
                "email": factories.User.stub().email,
                "save": "",
                "old_password": "Wrong-pass1",
                "password1": "",
                "password2": "",
            },
            extra_environ=env
        )
        assert "Old Password: incorrect password" in response

    def test_email_change_with_password(self, app, user):
        env = {"Authorization": user["token"]}
        response = app.post(
            url=url_for("user.edit"),
            data={
                "email": factories.User.stub().email,
                "save": "",
                "old_password": "correct123",
                "password1": "",
                "password2": "",
                "name": user["name"],
            },
            extra_environ=env
        )
        assert "Profile updated" in response

    def test_email_change_on_existed_email(self, app, user):
        user2 = factories.User(email="existed@email.com")
        env = {"Authorization": user["token"]}

        response = app.post(
            url=url_for("user.edit"),
            data={
                "email": user2["email"],
                "save": "",
                "old_password": "correct123",
                "password1": "",
                "password2": "",
                "name": user["name"],
            },
            extra_environ=env
        )
        assert "belongs to a registered user" in response

    def test_edit_user_logged_in_username_change(self, app, user):

        env = {"Authorization": user["token"]}
        response = app.post(
            url=url_for("user.edit"),
            data={
                "email": user["email"],
                "save": "",
                "password1": "",
                "password2": "",
                "name": factories.User.stub().name,
            },
            extra_environ=env
        )

        assert "That login name can not be modified" in response

    def test_edit_user_logged_in_username_change_by_name(self, app, user):

        env = {"Authorization": user["token"]}
        response = app.post(
            url=url_for("user.edit", id=user["name"]),
            data={
                "email": user["email"],
                "save": "",
                "password1": "",
                "password2": "",
                "name": factories.User.stub().name,
            },
            extra_environ=env
        )

        assert "That login name can not be modified" in response

    def test_edit_user_logged_in_username_change_by_id(self, app, user):

        env = {"Authorization": user["token"]}
        response = app.post(
            url=url_for("user.edit", id=user["id"]),
            data={
                "email": user["email"],
                "save": "",
                "password1": "",
                "password2": "",
                "name": factories.User.stub().name,
            },
            extra_environ=env
        )

        assert "That login name can not be modified" in response

    def test_perform_reset_for_key_change(self, app):
        password = "TestPassword1"
        params = {"password1": password, "password2": password}
        user = factories.User()
        user_obj = helpers.model.User.by_name(user["name"])
        create_reset_key(user_obj)
        key = user_obj.reset_key

        offset = url_for(
            "user.perform_reset",
            id=user_obj.id,
            key=user_obj.reset_key,
        )
        app.post(offset, data=params)
        user_obj = helpers.model.User.by_name(user["name"])  # Update user_obj

        assert key != user_obj.reset_key

    def test_password_reset_correct_password(self, app, user):
        """
        user password reset attempted with correct old password
        """
        env = {"Authorization": user["token"]}
        response = app.post(
            url=url_for("user.edit"),
            data={
                "save": "",
                "old_password": "correct123",
                "password1": "NewPassword1",
                "password2": "NewPassword1",
                "name": user["name"],
                "email": user["email"],
            },
            extra_environ=env
        )

        assert "Profile updated" in response

    def test_password_reset_incorrect_password(self, app, user):
        """
        user password reset attempted with invalid old password
        """
        env = {"Authorization": user["token"]}
        response = app.post(
            url=url_for("user.edit"),
            data={
                "save": "",
                "old_password": "Wrong-Pass1",
                "password1": "NewPassword1",
                "password2": "NewPassword1",
                "name": user["name"],
                "email": user["email"],
            },
            extra_environ=env
        )
        assert "Old Password: incorrect password" in response

    def test_user_follow(self, app, user):

        user_two = factories.User()
        env = {"Authorization": user["token"]}
        follow_url = url_for("user.follow", id=user_two["id"])
        response = app.post(follow_url, extra_environ=env)
        assert (
            "You are now following {0}".format(user_two["display_name"])
            in response
        )

    def test_user_follow_not_exist(self, app, user):
        """Pass an id for a user that doesn't exist"""
        env = {"Authorization": user["token"]}
        follow_url = url_for("user.follow", id="not-here")
        response = app.post(follow_url, extra_environ=env)

        assert response.status_code == 404

    def test_user_unfollow(self, app, user):

        user_two = factories.User()
        env = {"Authorization": user["token"]}
        follow_url = url_for("user.follow", id=user_two["id"])
        app.post(follow_url, extra_environ=env)

        unfollow_url = url_for("user.unfollow", id=user_two["id"])
        unfollow_response = app.post(unfollow_url, extra_environ=env)

        assert (
            "You are no longer following {0}".format(user_two["display_name"])
            in unfollow_response
        )

    def test_user_unfollow_not_following(self, app, user):
        """Unfollow a user not currently following"""

        user_two = factories.User()
        env = {"Authorization": user["token"]}
        unfollow_url = url_for("user.unfollow", id=user_two["id"])
        unfollow_response = app.post(unfollow_url, extra_environ=env)

        assert (
            "You are not following {0}".format(user_two["id"])
            in unfollow_response
        )

    def test_user_unfollow_not_exist(self, app, user):
        """Unfollow a user that doesn't exist."""
        env = {"Authorization": user["token"]}
        unfollow_url = url_for("user.unfollow", id="not-here")
        response = app.post(unfollow_url, extra_environ=env)

        assert response.status_code == 404

    def test_user_follower_list(self, app, sysadmin):
        """Following users appear on followers list page."""
        env = {"Authorization": sysadmin["token"]}

        user_two = factories.User()

        follow_url = url_for("user.follow", id=user_two["id"])
        app.post(follow_url, extra_environ=env)

        followers_url = url_for("user.followers", id=user_two["id"])

        # Only sysadmins can view the followers list pages
        followers_response = app.get(followers_url, extra_environ=env, status=200)
        assert sysadmin["display_name"] in followers_response

    def test_user_page_anon_access(self, app):
        """Anon users can access the user list page"""

        user_url = url_for("user.index")
        user_response = app.get(user_url, status=200)
        assert "<title>All Users - CKAN</title>" in user_response

    def test_user_page_lists_users(self, app):
        """/users/ lists registered users"""
        initial_user_count = model.User.count()
        factories.User(fullname="User One")
        factories.User(fullname="User Two")
        factories.User(fullname="User Three")

        user_url = url_for("user.index")
        user_response = app.get(user_url, status=200)

        user_response_html = BeautifulSoup(user_response.data)
        user_list = user_response_html.select("ul.user-list li")
        assert len(user_list) == 3 + initial_user_count

        user_names = [u.text.strip() for u in user_list]
        assert "User One" in user_names
        assert "User Two" in user_names
        assert "User Three" in user_names

    def test_user_page_doesnot_list_deleted_users(self, app):
        """/users/ doesn't list deleted users"""
        initial_user_count = model.User.count()

        factories.User(fullname="User One", state="deleted")
        factories.User(fullname="User Two")
        factories.User(fullname="User Three")

        user_url = url_for("user.index")
        user_response = app.get(user_url, status=200)

        user_response_html = BeautifulSoup(user_response.data)
        user_list = user_response_html.select("ul.user-list li")
        assert len(user_list) == 2 + initial_user_count

        user_names = [u.text.strip() for u in user_list]
        assert "User One" not in user_names
        assert "User Two" in user_names
        assert "User Three" in user_names

    def test_user_page_anon_search(self, app):
        """Anon users can search for users by username."""

        factories.User(fullname="User One", email="useroneemail@example.com")
        factories.User(fullname="Person Two")
        factories.User(fullname="Person Three")

        user_url = url_for("user.index")
        search_response = app.get(user_url, query_string={"q": "Person"})

        search_response_html = BeautifulSoup(search_response.data)
        user_list = search_response_html.select("ul.user-list li")
        assert len(user_list) == 2

        user_names = [u.text.strip() for u in user_list]
        assert "Person Two" in user_names
        assert "Person Three" in user_names
        assert "User One" not in user_names

    def test_user_page_anon_search_not_by_email(self, app):
        """Anon users can not search for users by email."""

        factories.User(fullname="User One", email="useroneemail@example.com")
        factories.User(fullname="Person Two")
        factories.User(fullname="Person Three")

        user_url = url_for("user.index")
        search_response = app.get(
            user_url, query_string={"q": "useroneemail@example.com"}
        )

        search_response_html = BeautifulSoup(search_response.data)
        user_list = search_response_html.select("ul.user-list li")
        assert len(user_list) == 0

    def test_user_page_sysadmin_user(self, app, sysadmin):
        """Sysadmin can search for users by email."""
        env = {"Authorization": sysadmin["token"]}
        stub = factories.User.stub()
        factories.User(fullname="User One", email=stub.email)
        factories.User(fullname="Person Two")
        factories.User(fullname="Person Three")

        user_url = url_for("user.index")
        search_response = app.get(
            user_url,
            query_string={"q": stub.email},
            extra_environ=env,
        )

        search_response_html = BeautifulSoup(search_response.data)
        user_list = search_response_html.select("ul.user-list li")
        assert len(user_list) == 1
        assert user_list[0].text.strip() == "User One"

    def test_simple(self, app):
        """Checking the template shows the activity stream."""

        user = factories.User()

        url = url_for("user.activity", id=user["id"])
        response = app.get(url)
        assert user["fullname"] in response
        assert "signed up" in response

    def test_create_user(self, app):

        user = factories.User()

        url = url_for("user.activity", id=user["id"])
        response = app.get(url)
        assert (
            '<a href="/user/{}">{}'.format(user["name"], user["fullname"]) in response
        )
        assert "signed up" in response

    def test_change_user(self, app):

        user = factories.User()
        _clear_activities()
        user["fullname"] = "Mr. Changed Name"
        helpers.call_action(
            "user_update", context={"user": user["name"]}, **user
        )

        url = url_for("user.activity", id=user["id"])
        response = app.get(url)
        assert (
            '<a href="/user/{}">{}'.format(user["name"], user["fullname"])
            in response
        )
        assert "updated their profile" in response

    def test_create_dataset(self, app):

        user = factories.User()
        _clear_activities()
        dataset = factories.Dataset(user=user)

        url = url_for("user.activity", id=user["id"])
        response = app.get(url)
        page = BeautifulSoup(response.body)
        href = page.select_one(".dataset")
        assert (
            '<a href="/user/{}">{}'.format(user["name"], user["fullname"]) in response
        )
        assert "created the dataset" in response
        assert dataset["id"] in href.select_one("a")["href"].split("/", 2)[-1]
        assert dataset["title"] in href.text.strip()

    def test_change_dataset(self, app):

        user = factories.User()
        dataset = factories.Dataset(user=user)
        _clear_activities()
        dataset["title"] = "Dataset with changed title"
        helpers.call_action(
            "package_update", context={"user": user["name"]}, **dataset
        )

        url = url_for("user.activity", id=user["id"])
        response = app.get(url)
        page = BeautifulSoup(response.body)
        href = page.select_one(".dataset")

        assert (
            '<a href="/user/{}">{}'.format(user["name"], user["fullname"]) in response
        )
        assert "updated the dataset" in response
        assert dataset["id"] in href.select_one("a")["href"].split("/", 2)[-1]
        assert dataset["title"] in href.text.strip()

    def test_delete_dataset(self, app, user):
        env = {"Authorization": user["token"]}
        dataset = factories.Dataset(user=user)
        _clear_activities()
        helpers.call_action(
            "package_delete", context={"user": user["name"]}, **dataset
        )

        url = url_for("user.activity", id=user["id"])
        response = app.get(url, extra_environ=env)
        page = BeautifulSoup(response.body)
        href = page.select_one(".dataset")
        assert (
            '<a href="/user/{}">{}'.format(
                user["name"], user["fullname"]) in response
        )
        assert "deleted the dataset" in response
        assert dataset["id"] in href.select_one("a")["href"].split("/", 2)[-1]
        assert dataset["title"] in href.text.strip()

    def test_create_group(self, app):

        user = factories.User()
        group = factories.Group(user=user)

        url = url_for("user.activity", id=user["id"])
        response = app.get(url)
        page = BeautifulSoup(response.body)
        href = page.select_one(".group")

        assert (
            '<a href="/user/{}">{}'.format(user["name"], user["fullname"]) in response
        )
        assert "created the group" in response
        assert group["id"] in href.select_one("a")["href"].split("/", 2)[-1]
        assert group["title"] in href.text.strip()

    def test_change_group(self, app):

        user = factories.User()
        group = factories.Group(user=user)
        _clear_activities()
        group["title"] = "Group with changed title"
        helpers.call_action(
            "group_update", context={"user": user["name"]}, **group
        )

        url = url_for("user.activity", id=user["id"])
        response = app.get(url)
        page = BeautifulSoup(response.body)
        href = page.select_one(".group")
        assert (
            '<a href="/user/{}">{}'.format(user["name"], user["fullname"]) in response
        )
        assert "updated the group" in response
        assert group["id"] in href.select_one("a")["href"].split("/", 2)[-1]
        assert group["title"] in href.text.strip()

    def test_delete_group_using_group_delete(self, app):

        user = factories.User()
        group = factories.Group(user=user)
        _clear_activities()
        helpers.call_action(
            "group_delete", context={"user": user["name"]}, **group
        )

        url = url_for("user.activity", id=user["id"])
        response = app.get(url)
        page = BeautifulSoup(response.body)
        href = page.select_one(".group")
        assert (
            '<a href="/user/{}">{}'.format(user["name"], user["fullname"]) in response
        )
        assert "deleted the group" in response
        assert group["id"] in href.select_one("a")["href"].split("/", 2)[-1]
        assert group["title"] in href.text.strip()

    def test_delete_group_by_updating_state(self, app, user):
        env = {"Authorization": user["token"]}
        group = factories.Group(user=user)
        _clear_activities()
        group["state"] = "deleted"
        helpers.call_action(
            "group_update",
            context={"user": user["name"]},
            **group
        )

        url = url_for("group.activity", id=group["id"])
        response = app.get(url, extra_environ=env)
        assert (
            '<a href="/user/{}">{}'.format(
                user["name"], user["fullname"]) in response
        )
        assert "deleted the group" in response
        assert (
            '<a href="/group/{}">{}'.format(group["name"], group["title"]) in response
        )

    @mock.patch("ckan.lib.mailer.send_reset_link")
    def test_request_reset_by_email(self, send_reset_link, app):
        user = factories.User()

        offset = url_for("user.request_reset")
        response = app.post(offset, data=dict(user=user["email"]))

        assert "A reset link has been emailed to you" in response
        assert send_reset_link.call_args[0][0].id == user["id"]

    @mock.patch("ckan.lib.mailer.send_reset_link")
    def test_request_reset_by_name(self, send_reset_link, app):
        user = factories.User()

        offset = url_for("user.request_reset")
        response = app.post(offset, data=dict(user=user["name"]))

        assert "A reset link has been emailed to you" in response
        assert send_reset_link.call_args[0][0].id == user["id"]

    def test_request_reset_without_param(self, app):

        offset = url_for("user.request_reset")
        response = app.post(offset)

        assert "Email is required" in response

    @mock.patch("ckan.lib.mailer.send_reset_link")
    def test_request_reset_for_unknown_username(self, send_reset_link, app):

        offset = url_for("user.request_reset")
        response = app.post(offset, data=dict(user="unknown"))

        # doesn't reveal account does or doesn't exist
        assert "A reset link has been emailed to you" in response
        send_reset_link.assert_not_called()

    @mock.patch("ckan.lib.mailer.send_reset_link")
    def test_request_reset_for_unknown_email(self, send_reset_link, app):

        offset = url_for("user.request_reset")
        response = app.post(offset, data=dict(user=factories.User.stub().email))

        # doesn't reveal account does or doesn't exist
        assert "A reset link has been emailed to you" in response
        send_reset_link.assert_not_called()

    @mock.patch("ckan.lib.mailer.send_reset_link")
    def test_request_reset_but_mailer_not_configured(
        self, send_reset_link, app
    ):
        user = factories.User()

        offset = url_for("user.request_reset")
        # This is the exception when the mailer is not configured:
        send_reset_link.side_effect = MailerException(
            'SMTP server could not be connected to: "localhost" '
            "[Errno 111] Connection refused"
        )
        response = app.post(offset, data=dict(user=user["name"]))

        assert "Error sending the email" in response

    @mock.patch("flask_login.utils._get_user")
    def test_sysadmin_not_authorized(self, current_user, app):
        user = factories.User()
        user_obj = model.User.get(user["name"])
        # mock current_user
        current_user.return_value = user_obj
        app.post(
            url_for("user.sysadmin"),
            data={"username": user["name"], "status": "1"},
            status=403
        )

    def test_sysadmin_invalid_user(self, app, sysadmin):
        env = {"Authorization": sysadmin["token"]}
        app.post(
            url_for("user.sysadmin"),
            data={"username": "fred", "status": "1"},
            extra_environ=env,
            status=404,
        )

    @mock.patch("flask_login.utils._get_user")
    def test_sysadmin_promote_success(self, current_user, app):

        sysadmin = factories.Sysadmin()
        sysadmin_obj = model.User.get(sysadmin["name"])
        # mock current_user
        current_user.return_value = sysadmin_obj
        # create a normal user
        user = factories.User(fullname="Alice")

        # promote them
        resp = app.post(
            url_for("user.sysadmin"),
            data={"username": user["name"], "status": "1"},
            status=200,
        )
        assert "Promoted Alice to sysadmin" in resp.body

        # now they are a sysadmin
        userobj = model.User.get(user["id"])
        assert userobj.sysadmin

    @mock.patch('flask_login.utils._get_user')
    def test_sysadmin_revoke_success(self, current_user, app):
        sysadmin = factories.Sysadmin()
        sysadmin_obj = model.User.get(sysadmin["name"])
        # mock current_user
        current_user.return_value = sysadmin_obj
        # create another sysadmin
        user = factories.Sysadmin(fullname="Bob")

        # revoke their status
        resp = app.post(
            url_for("user.sysadmin"),
            data={"username": user["name"], "status": "0"},
            status=200,
        )
        assert "Revoked sysadmin permission from Bob" in resp.body

        # now they are not a sysadmin any more
        userobj = model.User.get(user["id"])
        assert not userobj.sysadmin

    def test_user_delete_redirects_to_user_index(self, app, sysadmin):
        env = {"Authorization": sysadmin["token"]}
        user = factories.User()
        url = url_for("user.delete", id=user["id"])

        redirect_url = url_for("user.index", qualified=True)
        res = app.post(url, extra_environ=env, follow_redirects=False)

        user = helpers.call_action("user_show", id=user["id"])
        assert user["state"] == "deleted"
        assert res.headers["Location"].startswith(redirect_url)

    def test_user_delete_by_unauthorized_user(self, app, user):
        user_one = factories.User()
        url = url_for("user.delete", id=user_one["id"])
        env = {"Authorization": user["token"]}

        app.post(url, extra_environ=env, status=403)

    def test_user_read_without_id(self, app):
        app.get("/user", status=200)

    def test_user_read_me_without_id(self, app):
        app.get("/user/me", status=302, follow_redirects=False)

    def test_perform_reset_user_password_link_key_incorrect(self, app, user):
        env = {"Authorization": user["token"]}
        url = url_for("user.perform_reset", id=user["id"], key="randomness")
        app.get(url, extra_environ=env, status=403)

    def test_perform_reset_user_password_link_key_missing(self, app, user):
        env = {"Authorization": user["token"]}
        url = url_for("user.perform_reset", id=user["id"])
        app.get(url, extra_environ=env, status=403)

    def test_perform_reset_user_password_link_user_incorrect(self, app):
        factories.User()
        url = url_for(
            "user.perform_reset",
            id="randomness",
            key="randomness",
        )
        app.get(url, status=404)

    def test_perform_reset_activates_pending_user(self, app):
        password = "TestPassword1"
        params = {"password1": password, "password2": password}
        user = factories.User(state="pending")
        userobj = model.User.get(user["name"])
        create_reset_key(userobj)
        assert userobj.is_pending(), userobj.state

        url = url_for(
            "user.perform_reset",
            id=userobj.id,
            key=userobj.reset_key,
        )
        app.post(url, params=params)

        userobj = model.User.get(userobj.id)
        assert userobj.is_active()

    @mock.patch("flask_login.utils._get_user")
    def test_perform_reset_doesnt_activate_deleted_user(self, current_user, app):
        password = "TestPassword1"
        params = {"password1": password, "password2": password}
        user = factories.User()
        userobj = model.User.get(user["id"])
        userobj.delete()
        create_reset_key(userobj)
        assert userobj.is_deleted(), userobj.state

        url = url_for(
            "user.perform_reset",
            id=userobj.id,
            key=userobj.reset_key,
        )
        app.post(url, params=params, status=403)

        userobj = model.User.get(userobj.id)
        assert userobj.is_deleted(), userobj


@pytest.mark.usefixtures("non_clean_db")
class TestUserImage(object):
    def test_image_url_is_shown(self, app):

        user = factories.User(
            image_url="https://example.com/mypic.png", password="correct123")

        url = url_for("user.read", id=user["name"])

        user_token = factories.APIToken(user=user["name"])
        env = {"Authorization": user_token["token"]}
        res = app.get(url, environ_overrides=env)

        res_html = BeautifulSoup(res.data)
        user_images = res_html.select("img.user-image")

        assert len(user_images) == 2  # Logged in header + profile pic
        for img in user_images:
            assert img.attrs["src"] == "https://example.com/mypic.png"

    def test_fallback_to_gravatar(self, app):

        user = factories.User(image_url=None, password="correct123")

        url = url_for("user.read", id=user["name"])

        user_token = factories.APIToken(user=user["name"])
        env = {"Authorization": user_token["token"]}
        res = app.get(url, environ_overrides=env)

        res_html = BeautifulSoup(res.data)
        user_images = res_html.select("img.user-image")

        assert len(user_images) == 2  # Logged in header + profile pic
        for img in user_images:
            assert img.attrs["src"].startswith("//gravatar")

    @pytest.mark.ckan_config("ckan.gravatar_default", "disabled")
    def test_fallback_to_placeholder_if_gravatar_disabled(self, app):

        user = factories.User(image_url=None, password="correct123")

        url = url_for("user.read", id=user["name"])

        user_token = factories.APIToken(user=user["name"])
        env = {"Authorization": user_token["token"]}
        res = app.get(url, environ_overrides=env)

        res_html = BeautifulSoup(res.data)
        user_images = res_html.select("img.user-image")

        assert len(user_images) == 2  # Logged in header + profile pic
        for img in user_images:
            assert img.attrs["src"] == "/base/images/placeholder-user.png"
