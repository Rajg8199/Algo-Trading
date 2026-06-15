import type { Metadata } from "next";
import { Geist, Geist_Mono } from "next/font/google";

import { Providers } from "@/components/providers";

import "./globals.css";

const geistSans = Geist({ variable: "--font-geist-sans", subsets: ["latin"] });
const geistMono = Geist_Mono({ variable: "--font-geist-mono", subsets: ["latin"] });

export const metadata: Metadata = {
  title: "trading-platform console",
  description: "Quant research console — operations, experiments, backtests",
};

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    // suppressHydrationWarning: browser extensions (Grammarly, ColorZilla,
    // Bitdefender, etc.) inject attributes onto <html>/<body> before React
    // hydrates; that is the only diff here, so suppress it on these roots only.
    <html lang="en" suppressHydrationWarning>
      <head>
        {/* No-flash theme: apply the saved/system theme before first paint.
            Defaults to dark — the console's original look. */}
        <script
          dangerouslySetInnerHTML={{
            __html: `(function(){try{var t=localStorage.getItem("theme");if(!t){t=window.matchMedia("(prefers-color-scheme: light)").matches?"light":"dark";}document.documentElement.classList.toggle("dark",t!=="light");}catch(e){document.documentElement.classList.add("dark");}})();`,
          }}
        />
        {/* Strip attributes injected by browser extensions (Bitdefender's
            `bis_skin_checked`, Grammarly, etc.) BEFORE React hydrates, so they
            don't trigger hydration-mismatch warnings. Runs in <head> so the
            observer is live during the hydration window; harmless in prod. */}
        <script
          dangerouslySetInnerHTML={{
            __html: `(function(){try{var A=["bis_skin_checked","bis_register","__processed_"+"bis","data-new-gr-c-s-check-loaded","data-gr-ext-installed"];function clean(n){if(n&&n.nodeType===1){for(var i=0;i<A.length;i++){if(n.hasAttribute(A[i]))n.removeAttribute(A[i]);}}}var mo=new MutationObserver(function(ms){for(var i=0;i<ms.length;i++){var m=ms[i];if(m.type==="attributes"){clean(m.target);}else if(m.addedNodes){for(var j=0;j<m.addedNodes.length;j++)clean(m.addedNodes[j]);}}});mo.observe(document.documentElement,{subtree:true,childList:true,attributes:true,attributeFilter:A});}catch(e){}})();`,
          }}
        />
      </head>
      <body
        className={`${geistSans.variable} ${geistMono.variable} antialiased`}
        suppressHydrationWarning
      >
        <Providers>{children}</Providers>
      </body>
    </html>
  );
}
