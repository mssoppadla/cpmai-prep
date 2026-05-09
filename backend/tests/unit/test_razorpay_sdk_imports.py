"""Regression: razorpay SDK must import cleanly.

Bug history: razorpay 1.4.2's `client.py` does `import pkg_resources`,
which lives in setuptools. setuptools 80 dropped pkg_resources, so any
fresh install with default setuptools (>=80 since early 2025) raises
`ModuleNotFoundError: No module named 'pkg_resources'` at import time.

In our codebase that ImportError used to surface as the misleading
"razorpay package not installed" message in the admin "Test" button —
admins thought the package was missing when really setuptools just
needed pinning.

Fix: requirements.txt pins `setuptools<80`. This test confirms the
pin is honored on every install (CI, local dev, prod image build).
If razorpay is upgraded to 2.x in the future (which dropped the
pkg_resources dep), this test still passes — the pin can be removed
once the SDK bump is verified.
"""


def test_razorpay_sdk_imports():
    """A bare import + Client() must not raise.
    If this fails: requirements.txt's setuptools pin was lost OR the
    razorpay version was bumped without verifying transitive deps."""
    import razorpay
    razorpay.Client(auth=("dummy_key", "dummy_secret"))


def test_pkg_resources_available():
    """Direct check on the dep that historically went missing — gives
    a clearer failure message than the razorpay test if setuptools is
    the problem."""
    import pkg_resources                                 # noqa: F401


def test_provider_construct_does_not_eat_real_error():
    """If something IS broken with the SDK, RazorpayProvider's error
    message must surface the actual exception type, not a misleading
    'package not installed' fixed-string."""
    from app.services.razorpay_service import RazorpayProvider
    # Happy path — should NOT raise (the real fix). If it does, the
    # error message must include the real exception class name so
    # operators can debug.
    try:
        RazorpayProvider(key_id="rzp_test_x", key_secret="y", mode="test")
    except RuntimeError as e:
        # If razorpay SDK is broken in this env, surface the cause
        # explicitly — not the generic phrase.
        assert "razorpay package not installed" not in str(e), (
            "Error message hides the real cause. Surface the real "
            "ImportError so operators don't chase the wrong fix.")
