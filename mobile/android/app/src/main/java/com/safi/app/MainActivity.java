package com.safi.app;

import android.os.Bundle;
import android.webkit.WebView;
import com.getcapacitor.BridgeActivity;

public class MainActivity extends BridgeActivity {

  @Override
  public void onCreate(Bundle savedInstanceState) {
    super.onCreate(savedInstanceState);

    WebView wv = getBridge().getWebView();
    if (wv != null) {
      wv.setVerticalScrollBarEnabled(false);
      wv.setHorizontalScrollBarEnabled(false);
    }
  }
}
