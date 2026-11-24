from django.contrib.auth import get_user_model
from django.test import TestCase

from apps.institutes.psy_institute.models import TherapistProfile
from apps.modules.reviews.services import ReviewsError, record_review, reviews_for_target
from apps.kernel.tenancy.models import Institute

User = get_user_model()


class ReviewIsolationTests(TestCase):
    def test_a_target_cannot_be_reviewed_under_another_institute(self):
        family = Institute.objects.create(slug="family", name="خانواده", is_active=True)
        psy = Institute.objects.get(slug="psy")
        user = User.objects.create_user(username="review_target", password="x")
        profile = TherapistProfile.objects.create(
            user=user,
            display_name="خانواده",
            institute=family,
        )
        with self.assertRaises(ReviewsError):
            record_review(institute=psy, author=user, target=profile, rating=5, body="نه")
        own = record_review(institute=family, author=user, target=profile, rating=4, body="بله")
        self.assertEqual(list(reviews_for_target(psy, profile)), [])
        self.assertEqual(list(reviews_for_target(family, profile)), [own])
