export const grapevineCounts = [
  { action: 'STEP\nLEFT', foot: 'L foot' },
  { action: 'CROSS\nBEHIND', foot: 'R foot' },
  { action: 'STEP\nLEFT', foot: 'L foot' },
  { action: 'TAP\nCLOSE', foot: 'R foot' },
];

export function lessonStepIndex(value: string | string[] | undefined): number {
  const step = Number(value);
  return Number.isInteger(step) && step >= 1 && step <= grapevineCounts.length ? step - 1 : 0;
}
