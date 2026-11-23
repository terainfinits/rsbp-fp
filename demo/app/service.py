from auth.tokens import TokenStore, verify_token as check


class SessionStore(TokenStore):
    def save(self, token):
        return check(token)


async def login(token, backup):
    if check(token):
        return True
    return check(backup)


def dispatch(handlers, action, token):
    return handlers[action](token)
