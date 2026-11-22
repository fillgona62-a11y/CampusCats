package campus.cats;

import android.app.Activity;
import android.os.Bundle;
import android.content.ActivityNotFoundException;
import android.content.Intent;
import android.graphics.Color;
import android.graphics.Typeface;
import android.net.Uri;
import android.view.Gravity;
import android.view.inputmethod.EditorInfo;
import android.widget.*;
import java.net.URI;

/** The browser tab supplies system camera, gallery and web permissions. */
public final class MainActivity extends Activity {
    private static final int INK = Color.rgb(25, 61, 50);
    private EditText server;
    private TextView message;

    private int dp(int value) { return Math.round(getResources().getDisplayMetrics().density * value); }

    @Override public void onCreate(Bundle state) {
        super.onCreate(state);
        getWindow().setStatusBarColor(INK);
        LinearLayout form = new LinearLayout(this);
        form.setOrientation(LinearLayout.VERTICAL);
        form.setPadding(dp(26), dp(36), dp(26), dp(28));
        form.setGravity(Gravity.CENTER_VERTICAL);
        form.setBackgroundColor(Color.rgb(247, 246, 239));
        TextView title = new TextView(this);
        title.setText("猫迹");
        title.setTextSize(46);
        title.setTextColor(INK);
        title.setTypeface(Typeface.SERIF, Typeface.BOLD);
        form.addView(title);
        TextView hint = new TextView(this);
        hint.setText("连接学校的猫图鉴");
        hint.setTextSize(22);
        hint.setPadding(0, dp(14), 0, dp(18));
        form.addView(hint);
        server = new EditText(this);
        server.setSingleLine(true);
        server.setInputType(android.text.InputType.TYPE_CLASS_TEXT | android.text.InputType.TYPE_TEXT_VARIATION_URI);
        server.setHint("学校提供的 HTTPS 地址");
        server.setContentDescription("图鉴服务地址");
        int originId = getResources().getIdentifier("campus_origin", "string", getPackageName());
        String configured = originId == 0 ? "" : getString(originId);
        String saved = getPreferences(MODE_PRIVATE).getString("origin", configured);
        server.setText(saved);
        form.addView(server);
        Button enter = new Button(this);
        enter.setText("进入校园图鉴");
        enter.setOnClickListener(v -> enter());
        form.addView(enter);
        server.setImeOptions(EditorInfo.IME_ACTION_GO);
        server.setOnEditorActionListener((v, action, event) -> {
            if (action != EditorInfo.IME_ACTION_GO) return false;
            enter(); return true;
        });
        message = new TextView(this);
        message.setText("首次使用请填写学校提供的地址。关闭图鉴页面可回到这里更换地址。");
        message.setPadding(0, dp(14), 0, 0);
        form.addView(message);
        setContentView(form);
        if (state == null && !saved.isEmpty()) enter();
    }

    private void enter() {
        try {
            URI url = new URI(server.getText().toString().trim());
            String host = url.getHost();
            boolean local = "localhost".equalsIgnoreCase(host) || "127.0.0.1".equals(host);
            boolean allowed = "https".equalsIgnoreCase(url.getScheme())
                || (local && "http".equalsIgnoreCase(url.getScheme()));
            if (host == null || !allowed || url.getUserInfo() != null || url.getQuery() != null
                    || url.getFragment() != null || !(url.getPath().isEmpty() || url.getPath().equals("/"))) {
                throw new IllegalArgumentException();
            }
            URI origin = new URI(url.getScheme(), null, host, url.getPort(), "/", null, null);
            Intent browse = new Intent(Intent.ACTION_VIEW, Uri.parse(origin.toASCIIString()));
            Bundle extras = new Bundle();
            extras.putBinder("android.support.customtabs.extra.SESSION", null);
            browse.putExtras(extras);
            browse.putExtra("android.support.customtabs.extra.TOOLBAR_COLOR", INK);
            startActivity(browse);
            getPreferences(MODE_PRIVATE).edit().putString("origin", origin.toASCIIString()).apply();
        } catch (ActivityNotFoundException e) {
            message.setText("请先启用设备上的浏览器，再打开图鉴。");
        } catch (Exception e) {
            server.setError("请输入完整的 HTTPS 服务地址。本机调试可使用 http://localhost:8765");
        }
    }
}
