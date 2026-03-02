from rest_framework.exceptions import APIException


class AMSSException(APIException):
    status_code = 400
    default_detail = "An error occurred in AMSS"
    default_code = "amss_error"
