# Instagram

[Manual](../README.md) · [Accounts and secrets](../02-accounts-and-secrets.md)

The Instagram slide shows our latest posts on a phone, with a QR code to the account. It reads them
with Meta's *Instagram API with Instagram Login*, which only works for a **professional** account
(Business or Creator; switch in the Instagram app under Settings → Account type and tools). One-time
setup:

1. Register as a Meta developer (once per Facebook account): logged into Facebook, go to
   https://developers.facebook.com/async/registration (or https://developers.facebook.com and
   **Get Started**), agree, and verify your phone number and email. Only then does the App
   Dashboard (https://developers.facebook.com/apps) work.
2. **Create First App** (at the end of the registration) or **Create App** in the App Dashboard:
   use case **Other**, app type **Business**, any name and your email. Skip connecting a business.
   In the new app, find the **Instagram** product and click **Set up**; this adds **API setup with
   Instagram login**.
3. There, under **Generate access tokens**, **Add account** and log in with our Instagram account
   (it must be public), then **Generate token** next to it and copy the token.
4. On the TV PC, copy `config/instagram.example.json` to `~/.config/slideshow/instagram.json` and
   paste the token in place of `PASTE-THE-TOKEN-FROM-META-HERE` (keep the quotes):
   `mkdir -p ~/.config/slideshow && cp config/instagram.example.json ~/.config/slideshow/instagram.json`

The slideshow renews the token every week by itself (a token is valid for 60 days), and writes the
new one to that file, so it keeps working. If the slide disappears and http://127.0.0.1:8080/status
shows an Instagram error (e.g. the TV PC was off for two months, or the password changed), generate
a new token as in step 3. The app can stay in development mode (no App Review, no business
verification): it only reads our own account, which is added to it as a tester in step 3.
