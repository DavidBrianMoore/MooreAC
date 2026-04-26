from firebase_functions import https_fn
from server import app as flask_app

@https_fn.on_request()
def app(req: https_fn.Request) -> https_fn.Response:
    """
    Wrap the Flask app for Firebase Functions Gen 2.
    """
    with flask_app.request_context(req.environ):
        return flask_app.full_dispatch_request()
