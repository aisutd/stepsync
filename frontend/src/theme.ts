// Colors sampled from the StepSync Figma design (cream, ink and bronze).
export const colors = {
  background: '#F6EFE6',
  surface: '#F9F3EC',
  surfaceAlt: '#F3E9DE',
  border: '#CBC1B4',
  hairline: '#E8E1D7',
  text: '#141210',
  muted: '#807A73',
  accent: '#8F6845', // "Better." headline, active tab
  accentSoft: '#C4976F', // progress ring and bars
  pill: '#F5E8D9',
  pillText: '#A38062',
  primary: '#0F0E0D', // black buttons
  onPrimary: '#FFFFFF',
  good: '#2F8F5B',
  okay: '#B7791F',
  bad: '#C0392B',
};

export const radius = { sm: 10, md: 14, lg: 20, pill: 999 };

export function scoreColor(score: number): string {
  if (score >= 85) return colors.good;
  if (score >= 70) return colors.okay;
  return colors.bad;
}
