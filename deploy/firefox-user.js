// Firefox settings for the kiosk profile (data/kiosk-firefox-profile); kiosk.sh copies this in at every start.
// Nothing may cover the slideshow: no first-run pages, questions, restore pages or update prompts.
user_pref("browser.aboutwelcome.enabled", false);
user_pref("browser.startup.homepage_override.mstone", "ignore");
user_pref("startup.homepage_welcome_url", "");
user_pref("startup.homepage_welcome_url.additional", "");
user_pref("browser.shell.checkDefaultBrowser", false);
user_pref("datareporting.policy.dataSubmissionPolicyBypassNotification", true);
user_pref("datareporting.healthreport.uploadEnabled", false);
user_pref("toolkit.telemetry.reportingpolicy.firstRun", false);
user_pref("browser.sessionstore.resume_from_crash", false);
user_pref("app.update.auto", false);
user_pref("browser.translations.automaticallyPopup", false);
user_pref("extensions.pocket.enabled", false);
// Slides may play sound without anyone clicking first.
user_pref("media.autoplay.default", 0);
