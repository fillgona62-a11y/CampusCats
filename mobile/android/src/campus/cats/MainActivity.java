package campus.cats;

import android.Manifest;
import android.app.Activity;
import android.content.ActivityNotFoundException;
import android.content.ClipData;
import android.content.Intent;
import android.content.pm.PackageManager;
import android.graphics.Color;
import android.net.Uri;
import android.os.Bundle;
import android.provider.MediaStore;
import android.util.Base64;
import android.view.View;
import android.view.WindowInsets;
import android.webkit.*;
import android.widget.FrameLayout;
import android.widget.Toast;
import java.io.*;
import java.util.Arrays;

public final class MainActivity extends Activity {
    private static final String ENTRY = "/_app/index.html";
    private static final int CAMERA = 11, PICK = 12, EXPORT = 13, TAKE = 14, LOCATION = 15;
    private WebView web;
    private Uri origin, captureUri;
    private PermissionRequest cameraRequest;
    private GeolocationPermissions.Callback geoCallback;
    private String geoOrigin;
    private ValueCallback<Uri[]> chooser;
    private File exportFile;
    private boolean systemCamera;

    private Uri defaultOrigin() {
        return Uri.parse(getString(getResources().getIdentifier("campus_origin", "string", getPackageName())));
    }
    private static Uri parseHttpsOrigin(String text) {
        if (text == null) return null;
        String trimmed = text.trim();
        if (trimmed.isEmpty()) return null;
        Uri u = Uri.parse(trimmed);
        if (!"https".equalsIgnoreCase(u.getScheme()) || u.getHost() == null || u.getHost().isEmpty()
            || u.getUserInfo() != null || u.getQuery() != null || u.getFragment() != null) return null;
        String p = u.getPath();
        if (p != null && !p.isEmpty() && !"/".equals(p)) return null;
        return Uri.parse("https://" + u.getEncodedAuthority());
    }
    private Uri resolveOrigin() {
        String custom = getSharedPreferences("campuscats", MODE_PRIVATE).getString("origin", null);
        Uri parsed = parseHttpsOrigin(custom);
        return parsed != null ? parsed : defaultOrigin();
    }

    @Override public void onCreate(Bundle state) {
        super.onCreate(state);
        origin = resolveOrigin();
        web = new WebView(this);
        web.setBackgroundColor(Color.rgb(247,246,238));
        getWindow().setStatusBarColor(Color.rgb(247,246,238));
        getWindow().setNavigationBarColor(Color.rgb(247,246,238));
        web.setSystemUiVisibility(View.SYSTEM_UI_FLAG_LIGHT_STATUS_BAR | View.SYSTEM_UI_FLAG_LIGHT_NAVIGATION_BAR);
        FrameLayout screen = new FrameLayout(this);
        screen.setBackgroundColor(Color.rgb(247,246,238));
        screen.addView(web);
        if (android.os.Build.VERSION.SDK_INT >= 35) {
            screen.setOnApplyWindowInsetsListener((v, insets) -> {
                android.graphics.Insets bars = insets.getInsets(WindowInsets.Type.systemBars() | WindowInsets.Type.displayCutout() | WindowInsets.Type.ime());
                v.setPadding(bars.left,bars.top,bars.right,bars.bottom);
                return WindowInsets.CONSUMED;
            });
        }
        setContentView(screen);
        WebSettings settings = web.getSettings();
        settings.setJavaScriptEnabled(true);
        settings.setDomStorageEnabled(true);
        settings.setGeolocationEnabled(true);
        settings.setAllowFileAccess(false);
        settings.setAllowContentAccess(false);
        settings.setMixedContentMode(WebSettings.MIXED_CONTENT_NEVER_ALLOW);
        CookieManager.getInstance().setAcceptCookie(true);
        CookieManager.getInstance().setAcceptThirdPartyCookies(web,false);
        web.setWebViewClient(new LocalClient());
        web.setWebChromeClient(new Chrome());
        String page = state == null ? null : state.getString("page");
        if (state != null && state.getString("export") != null)
            exportFile = new File(getCacheDir(), new File(state.getString("export")).getName());
        web.loadUrl(page != null && isEntry(Uri.parse(page)) ? page : origin + ENTRY);
    }

    private boolean trusted(Uri url) {
        return url != null && "https".equals(url.getScheme()) && origin.getEncodedAuthority().equals(url.getEncodedAuthority());
    }
    private boolean isEntry(Uri url) { return trusted(url) && ENTRY.equals(url.getPath()); }

    private static WebResourceResponse missing() {
        return new WebResourceResponse("text/plain","UTF-8",404,"Not Found",null,new ByteArrayInputStream(new byte[0]));
    }
    private class LocalClient extends WebViewClient {
        @Override public boolean shouldOverrideUrlLoading(WebView view, WebResourceRequest request) {
            return !isEntry(request.getUrl());
        }
        @Override public WebResourceResponse shouldInterceptRequest(WebView view, WebResourceRequest request) {
            Uri uri = request.getUrl();
            String path = uri.getEncodedPath();
            if (!trusted(uri) || path == null) return missing();
            if (!request.isForMainFrame() && (path.startsWith("/api/") || path.startsWith("/media/"))) return null;
            String name = ENTRY.equals(path) ? "index.html" : path.substring(1);
            if (!"GET".equals(request.getMethod()) || !name.matches("(?:assets/)?[A-Za-z0-9_-]+\\.[A-Za-z0-9]+")) return missing();
            String mime;
            if (name.endsWith(".js")) mime = "text/javascript";
            else if (name.endsWith(".html")) mime = "text/html";
            else if (name.endsWith(".css")) mime = "text/css";
            else if (name.endsWith(".jpg")) mime = "image/jpeg";
            else if (name.endsWith(".png")) mime = "image/png";
            else if (name.endsWith(".webmanifest")) mime = "application/manifest+json";
            else return missing();
            try {
                WebResourceResponse res = new WebResourceResponse(mime, mime.startsWith("image/") ? null : "UTF-8", getAssets().open(name));
                if (name.equals("index.html")) res.setResponseHeaders(java.util.Collections.singletonMap("Content-Security-Policy",
                    "default-src 'self'; script-src 'self' 'unsafe-inline' 'unsafe-eval' https://*.amap.com https://*.autonavi.com; style-src 'self' 'unsafe-inline'; img-src 'self' data: blob: https://*.amap.com https://*.autonavi.com; media-src 'self' blob:; connect-src 'self' blob: data: https://*.amap.com https://*.autonavi.com; frame-src 'none'; object-src 'none'; base-uri 'none'"));
                return res;
            } catch (IOException ex) { return missing(); }
        }
    }
    private class Chrome extends WebChromeClient {
        @Override public void onPermissionRequest(PermissionRequest req) {
            if (!trusted(req.getOrigin()) || !Arrays.asList(req.getResources()).contains(PermissionRequest.RESOURCE_VIDEO_CAPTURE)) { req.deny(); return; }
            if (cameraRequest != null) cameraRequest.deny();
            cameraRequest = req;
            requestCamera();
        }
        @Override public void onPermissionRequestCanceled(PermissionRequest req) {
            if (cameraRequest == req) cameraRequest = null;
        }
        @Override public void onGeolocationPermissionsShowPrompt(String reqOrigin, GeolocationPermissions.Callback callback) {
            if (!trusted(Uri.parse(reqOrigin))) { callback.invoke(reqOrigin, false, false); return; }
            if (checkSelfPermission(Manifest.permission.ACCESS_FINE_LOCATION) == PackageManager.PERMISSION_GRANTED
                || checkSelfPermission(Manifest.permission.ACCESS_COARSE_LOCATION) == PackageManager.PERMISSION_GRANTED) {
                callback.invoke(reqOrigin, true, false);
            } else {
                geoOrigin = reqOrigin;
                geoCallback = callback;
                requestPermissions(new String[]{Manifest.permission.ACCESS_FINE_LOCATION, Manifest.permission.ACCESS_COARSE_LOCATION}, LOCATION);
            }
        }
        @Override public boolean onShowFileChooser(WebView view, ValueCallback<Uri[]> callback, FileChooserParams params) {
            completeChooser(null);
            chooser = callback;
            if (params.isCaptureEnabled()) { systemCamera = true; requestCamera(); }
            else {
                Intent pick = new Intent(Intent.ACTION_OPEN_DOCUMENT).addCategory(Intent.CATEGORY_OPENABLE).setType("image/*");
                try { startActivityForResult(pick, PICK); } catch (ActivityNotFoundException ex) { completeChooser(null); }
            }
            return true;
        }
        @Override public boolean onJsPrompt(WebView view, String url, String message, String payload, JsPromptResult result) {
            if (!isEntry(Uri.parse(url))) return super.onJsPrompt(view,url,message,payload,result);
            if ("campuscats-origin:set".equals(message)) {
                Uri next = parseHttpsOrigin(payload);
                if (next == null) { result.cancel(); return true; }
                getSharedPreferences("campuscats", MODE_PRIVATE).edit().putString("origin", next.toString()).apply();
                origin = next;
                result.confirm(origin.toString());
                web.loadUrl(origin + ENTRY);
                return true;
            }
            if ("campuscats-origin:reset".equals(message)) {
                getSharedPreferences("campuscats", MODE_PRIVATE).edit().remove("origin").apply();
                origin = defaultOrigin();
                result.confirm(origin.toString());
                web.loadUrl(origin + ENTRY);
                return true;
            }
            if (!message.startsWith("campuscats-save:")) return super.onJsPrompt(view,url,message,payload,result);
            String filename = message.substring("campuscats-save:".length());
            boolean png = filename.endsWith(".png");
            if (exportFile != null || (!png && !filename.endsWith(".csv")) || payload == null || payload.length() > 12000000) {
                result.cancel(); return true;
            }
            try {
                exportFile = File.createTempFile("export-", ".tmp", getCacheDir());
                try (OutputStream out = new FileOutputStream(exportFile)) { out.write(Base64.decode(payload,Base64.DEFAULT)); }
                Intent save = new Intent(Intent.ACTION_CREATE_DOCUMENT).addCategory(Intent.CATEGORY_OPENABLE)
                    .setType(png ? "image/png" : "text/csv").putExtra(Intent.EXTRA_TITLE,new File(filename).getName());
                startActivityForResult(save, EXPORT);
                result.confirm("ok");
            } catch (IOException | RuntimeException ex) { clearExport(); result.cancel(); }
            return true;
        }
    }
    private void requestCamera() {
        if (checkSelfPermission(Manifest.permission.CAMERA) == PackageManager.PERMISSION_GRANTED) cameraDecision(true);
        else requestPermissions(new String[]{Manifest.permission.CAMERA}, CAMERA);
    }
    @Override public void onRequestPermissionsResult(int request, String[] permissions, int[] grants) {
        super.onRequestPermissionsResult(request,permissions,grants);
        if (request == CAMERA) cameraDecision(grants.length > 0 && grants[0] == PackageManager.PERMISSION_GRANTED);
        if (request == LOCATION && geoCallback != null) {
            boolean ok = grants.length > 0 && grants[0] == PackageManager.PERMISSION_GRANTED;
            geoCallback.invoke(geoOrigin, ok, false);
            geoCallback = null;
            geoOrigin = null;
        }
    }
    private void cameraDecision(boolean allowed) {
        if (cameraRequest != null) {
            if (allowed) cameraRequest.grant(new String[]{PermissionRequest.RESOURCE_VIDEO_CAPTURE}); else cameraRequest.deny();
            cameraRequest = null;
        }
        if (!systemCamera) return;
        systemCamera = false;
        if (!allowed) { completeChooser(null); return; }
        try {
            captureUri = CaptureFile.create(this);
            Intent intent = new Intent(MediaStore.ACTION_IMAGE_CAPTURE).putExtra(MediaStore.EXTRA_OUTPUT,captureUri);
            intent.setClipData(ClipData.newRawUri("photo",captureUri));
            intent.addFlags(Intent.FLAG_GRANT_READ_URI_PERMISSION | Intent.FLAG_GRANT_WRITE_URI_PERMISSION);
            startActivityForResult(intent,TAKE);
        } catch (IOException | RuntimeException ex) { completeChooser(null); }
    }
    private void completeChooser(Uri uri) {
        ValueCallback<Uri[]> previous = chooser;
        chooser = null;
        if (previous != null) previous.onReceiveValue(uri == null ? null : new Uri[]{uri});
    }
    private void clearExport() {
        if (exportFile != null) exportFile.delete();
        exportFile = null;
    }
    @Override protected void onActivityResult(int code,int result,Intent data) {
        super.onActivityResult(code,result,data);
        Uri selected = result == RESULT_OK && data != null ? data.getData() : null;
        if (code == PICK) completeChooser(selected != null && "content".equals(selected.getScheme()) && !CaptureFile.AUTH.equals(selected.getAuthority()) ? selected : null);
        if (code == TAKE) {
            if (captureUri != null) revokeUriPermission(captureUri,Intent.FLAG_GRANT_READ_URI_PERMISSION | Intent.FLAG_GRANT_WRITE_URI_PERMISSION);
            completeChooser(result == RESULT_OK ? captureUri : null);
            captureUri = null;
        }
        if (code == EXPORT && exportFile != null) {
            if (selected != null && "content".equals(selected.getScheme())) {
                try (InputStream in = new FileInputStream(exportFile); OutputStream out = getContentResolver().openOutputStream(selected,"w")) {
                    if (out == null) throw new IOException();
                    byte[] buffer = new byte[16384]; int read;
                    while ((read=in.read(buffer)) != -1) out.write(buffer,0,read);
                    Toast.makeText(this,"文件已保存",Toast.LENGTH_SHORT).show();
                } catch (IOException | RuntimeException ex) { Toast.makeText(this,"保存失败，请重试",Toast.LENGTH_SHORT).show(); }
            }
            clearExport();
        }
    }
    @Override protected void onSaveInstanceState(Bundle state) {
        super.onSaveInstanceState(state);
        state.putString("page",web.getUrl());
        if (exportFile != null) state.putString("export",exportFile.getName());
    }
    @Override protected void onPause() { super.onPause(); web.onPause(); CookieManager.getInstance().flush(); }
    @Override protected void onResume() { super.onResume(); if (web != null) web.onResume(); }
    @Override public void onBackPressed() {
        web.evaluateJavascript("(function(){var d=document.querySelector('dialog[open]'); if(d){d.close();return true;} return false;})()", closed -> {
            if ("true".equals(closed)) return;
            if (web.canGoBack()) web.goBack(); else super.onBackPressed();
        });
    }
    @Override protected void onDestroy() { completeChooser(null); web.destroy(); super.onDestroy(); }
}
