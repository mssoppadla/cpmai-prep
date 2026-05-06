/**
 * Type declarations for Google Identity Services (GIS).
 * https://developers.google.com/identity/gsi/web/reference/js-reference
 *
 * Only the surface this lib uses is declared. Extend as needed.
 */
export interface GoogleCredentialResponse {
  credential: string;
  select_by?: string;
  clientId?: string;
}

export interface GoogleIdConfig {
  client_id: string;
  callback: (response: GoogleCredentialResponse) => void;
  auto_select?: boolean;
  cancel_on_tap_outside?: boolean;
  use_fedcm_for_prompt?: boolean;
  ux_mode?: "popup" | "redirect";
  context?: "signin" | "signup" | "use";
}

export interface GsiButtonConfig {
  type?: "standard" | "icon";
  theme?: "outline" | "filled_blue" | "filled_black";
  size?: "large" | "medium" | "small";
  text?: "signin_with" | "signup_with" | "continue_with" | "signin";
  shape?: "rectangular" | "pill" | "circle" | "square";
  logo_alignment?: "left" | "center";
  width?: number;
  locale?: string;
}

export interface GsiAccountsId {
  initialize: (config: GoogleIdConfig) => void;
  renderButton: (parent: HTMLElement, options: GsiButtonConfig) => void;
  prompt: (notification?: (n: unknown) => void) => void;
  disableAutoSelect: () => void;
  cancel: () => void;
}

declare global {
  interface Window {
    google?: {
      accounts: {
        id: GsiAccountsId;
      };
    };
  }
}

export {};
