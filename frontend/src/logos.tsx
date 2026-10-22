import { useI18n } from "./i18n";
import { ExternalIcon } from "./icons";

// Brand marks as inline SVG: no extra request, and the 42 mark follows the text color.
export const Logo42 = () => (
  <svg viewBox="32 -51 896 629" fill="currentColor" aria-hidden="true">
    <polygon points="32,412.6 362.1,412.6 362.1,578 526.8,578 526.8,279.1 197.3,279.1 526.8,-51.1 362.1,-51.1 32,279.1" />
    <polygon points="597.9,114.2 762.7,-51.1 597.9,-51.1" />
    <polygon points="762.7,114.2 597.9,279.1 597.9,443.9 762.7,443.9 762.7,279.1 928,114.2 928,-51.1 762.7,-51.1" />
    <polygon points="928,279.1 762.7,443.9 928,443.9" />
  </svg>
);

// Letterboxd's three dots
export const LogoLetterboxd = () => (
  <svg viewBox="0 0 30 12" width="24" height="10" aria-hidden="true">
    <circle cx="6" cy="6" r="6" fill="#ff8000" />
    <circle cx="24" cy="6" r="6" fill="#40bcf4" />
    <circle cx="15" cy="6" r="6" fill="#00e054" fillOpacity=".95" />
  </svg>
);

// the film's page at Letterboxd (it redirects TMDb's id), where the member rates it and writes about it
export const LetterboxdLink = ({ tmdbId }: { tmdbId: number }) => {
  const { t } = useI18n();
  return (
    <a className="mark" href={`https://letterboxd.com/tmdb/${tmdbId}`} target="_blank" rel="noopener noreferrer">
      <LogoLetterboxd /> {t("modal.letterboxd")} <ExternalIcon />
    </a>
  );
};

export const LogoGoogle = () => (
  <svg viewBox="0 0 24 24" aria-hidden="true">
    <path fill="#4285F4" d="M22.56 12.25c0-.78-.07-1.53-.2-2.25H12v4.26h5.92c-.26 1.37-1.04 2.53-2.21 3.31v2.77h3.57c2.08-1.92 3.28-4.74 3.28-8.09z" />
    <path fill="#34A853" d="M12 23c2.97 0 5.46-.98 7.28-2.66l-3.57-2.77c-.98.66-2.23 1.06-3.71 1.06-2.86 0-5.29-1.93-6.16-4.53H2.18v2.84C3.99 20.53 7.7 23 12 23z" />
    <path fill="#FBBC05" d="M5.84 14.09c-.22-.66-.35-1.36-.35-2.09s.13-1.43.35-2.09V7.07H2.18C1.43 8.55 1 10.22 1 12s.43 3.45 1.18 4.93l2.85-2.22.81-.62z" />
    <path fill="#EA4335" d="M12 5.38c1.62 0 3.06.56 4.21 1.64l3.15-3.15C17.45 2.09 14.97 1 12 1 7.7 1 3.99 3.47 2.18 7.07l3.66 2.84c.87-2.6 3.3-4.53 6.16-4.53z" />
  </svg>
);

// round flags for the language menu, from the circle-flags set (MIT, github.com/HatScripts/circle-flags); drawn, because the flag emoji show as letters on Windows
export const FlagEN = () => (
  <svg className="flag" viewBox="0 0 512 512" width="24" height="24" aria-hidden="true">
    <mask id="flag-en"><circle cx="256" cy="256" r="256" fill="#fff" /></mask>
    <g mask="url(#flag-en)">
      <path fill="#eee" d="m0 0 8 22-8 23v23l32 54-32 54v32l32 48-32 48v32l32 54-32 54v68l22-8 23 8h23l54-32 54 32h32l48-32 48 32h32l54-32 54 32h68l-8-22 8-23v-23l-32-54 32-54v-32l-32-48 32-48v-32l-32-54 32-54V0l-22 8-23-8h-23l-54 32-54-32h-32l-48 32-48-32h-32l-54 32L68 0H0z" />
      <path fill="#0052b4" d="M336 0v108L444 0Zm176 68L404 176h108zM0 176h108L0 68ZM68 0l108 108V0Zm108 512V404L68 512ZM0 444l108-108H0Zm512-108H404l108 108Zm-68 176L336 404v108z" />
      <path fill="#d80027" d="M0 0v45l131 131h45L0 0zm208 0v208H0v96h208v208h96V304h208v-96H304V0h-96zm259 0L336 131v45L512 0h-45zM176 336 0 512h45l131-131v-45zm160 0 176 176v-45L381 336h-45z" />
    </g>
  </svg>
);
export const FlagFR = () => (
  <svg className="flag" viewBox="0 0 512 512" width="24" height="24" aria-hidden="true">
    <mask id="flag-fr"><circle cx="256" cy="256" r="256" fill="#fff" /></mask>
    <g mask="url(#flag-fr)">
      <path fill="#eee" d="M167 0h178l25.9 252.3L345 512H167l-29.8-253.4z" />
      <path fill="#0052b4" d="M0 0h167v512H0z" />
      <path fill="#d80027" d="M345 0h167v512H345z" />
    </g>
  </svg>
);
