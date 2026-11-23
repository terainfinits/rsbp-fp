TOKEN_DEMO = "demo"


def verify_token(token):
    return token == TOKEN_DEMO


class TokenStore:
    def save(self, token):
        return token
