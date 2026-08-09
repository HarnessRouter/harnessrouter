// iconify-icon web component (loaded client-side in the revamp Shell). React 19 moved the JSX
// namespace under the react module, so augment it there (the global JSX namespace is gone).
import 'react';

declare module 'react' {
  namespace JSX {
    interface IntrinsicElements {
      'iconify-icon': React.DetailedHTMLProps<React.HTMLAttributes<HTMLElement>, HTMLElement> & {
        icon: string;
        width?: string | number;
        height?: string | number;
      };
    }
  }
}
