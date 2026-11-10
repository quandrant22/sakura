/// <reference types="vite/client" />

/** Версия из package.json (vite.config.ts → define). */
declare const __APP_VERSION__: string;

declare namespace JSX {
  interface IntrinsicElements {
    webview: React.DetailedHTMLProps<React.HTMLAttributes<HTMLElement>, HTMLElement> & {
      src?: string;
      allowpopups?: boolean | string;
      webpreferences?: string;
      useragent?: string;
    };
  }
}
