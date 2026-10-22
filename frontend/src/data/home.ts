// Placeholder content for the home screen, matching the Figma mockup.
// Replace with real data from Supabase once progress and routines are stored there.
import type { ImageSourcePropType } from 'react-native';

export type Routine = {
  id: string;
  title: string;
  style: string;
  steps: number;
  image: ImageSourcePropType;
};

export const routines: Routine[] = [
  { id: 'perfect-night', title: 'Perfect Night', style: 'K-Pop', steps: 5, image: require('../../assets/images/routine-1.png') },
  { id: 'toosie-slide', title: 'Toosie Slide', style: 'Hip Hop', steps: 4, image: require('../../assets/images/routine-2.png') },
  { id: 'hip-hop-basics', title: 'Hip Hop Basics', style: 'Hip Hop', steps: 6, image: require('../../assets/images/routine-3.png') },
];

export const progress = {
  level: 3,
  movesCompleted: 12,
  movesTotal: 20,
};

export const continueWatching = {
  routineId: 'perfect-night',
  durationLabel: '1:39',
  fractionDone: 0.4,
};
