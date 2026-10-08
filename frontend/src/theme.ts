export const colors = {
  background: '#0E0F13',
  surface: '#1A1C23',
  border: '#2A2D38',
  text: '#F3F4F6',
  muted: '#9CA3AF',
  accent: '#7C5CFF',
  good: '#34D399',
  okay: '#FBBF24',
  bad: '#F87171',
};

export function scoreColor(score: number): string {
  if (score >= 85) return colors.good;
  if (score >= 70) return colors.okay;
  return colors.bad;
}
