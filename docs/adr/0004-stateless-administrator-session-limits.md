# Stateless administrator session limits

Administrator sessions are signed cookies with a 12-hour lifetime. Logout clears the current browser's cookie, but cannot revoke a copied cookie before expiry; changing the administrator password invalidates existing sessions. This avoids a server-side session store for the single-administrator deployment while making the revocation limit explicit.
