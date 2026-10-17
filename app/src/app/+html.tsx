// Web-only HTML shell for static rendering: page title, description and link-preview tags.
// Native apps never use this file.
import { ScrollViewStyleReset } from 'expo-router/html';
import type { PropsWithChildren } from 'react';

const TITLE = 'Runway';
const DESCRIPTION =
  'See the day your balance runs out before it happens — and let an AI banker fix it with one tap.';

export default function Root({ children }: PropsWithChildren) {
  return (
    <html lang="en">
      <head>
        <meta charSet="utf-8" />
        <meta httpEquiv="X-UA-Compatible" content="IE=edge" />
        <meta name="viewport" content="width=device-width, initial-scale=1, shrink-to-fit=no" />
        <title>{TITLE}</title>
        <meta name="description" content={DESCRIPTION} />
        <meta property="og:title" content={TITLE} />
        <meta property="og:description" content={DESCRIPTION} />
        <meta property="og:url" content="https://sixsevenbucksleft.vip" />
        <meta name="apple-mobile-web-app-title" content="Runway" />
        <ScrollViewStyleReset />
        {/* charcoal before the app paints, so the page never flashes white */}
        <style dangerouslySetInnerHTML={{ __html: 'html,body{background:#14181c;}' }} />
      </head>
      <body>{children}</body>
    </html>
  );
}
