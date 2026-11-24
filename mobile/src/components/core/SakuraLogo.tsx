/**
 * Цветок Сакуры: пять лепестков с вырезом на кончике и градиентом темы.
 * Порт desktop/ui/src/components/SakuraLogo.tsx для React Native SVG.
 */

import React, { useId } from 'react';
import Svg, { Circle, Defs, G, Path, RadialGradient, Stop } from 'react-native-svg';
import { SakuraColors } from '../../constants/colors';

const PETAL =
  'M0 -2.2C-3.6 -4.6 -5.6 -9.2 -3.9 -12.6C-2.9 -14.5 -1.2 -14.9 0 -13.4C1.2 -14.9 2.9 -14.5 3.9 -12.6C5.6 -9.2 3.6 -4.6 0 -2.2Z';

interface SakuraLogoProps {
  size?: number;
}

export const SakuraLogo: React.FC<SakuraLogoProps> = ({ size = 28 }) => {
  const uid = useId().replace(/:/g, '');
  const gradId = `sakuraPetal_${uid}`;

  return (
    <Svg width={size} height={size} viewBox="-15 -15 30 30">
      <Defs>
        <RadialGradient id={gradId} gradientUnits="userSpaceOnUse" cx="0" cy="0" r="15">
          <Stop offset="0.15" stopColor={SakuraColors.accent} />
          <Stop offset="1" stopColor={SakuraColors.accentDeep} />
        </RadialGradient>
      </Defs>
      <G fill={`url(#${gradId})`}>
        {[0, 72, 144, 216, 288].map((angle) => (
          <Path key={angle} d={PETAL} transform={`rotate(${angle})`} />
        ))}
      </G>
      <Circle r="2.4" fill={SakuraColors.accent} />
      {[0, 72, 144, 216, 288].map((angle) => (
        <Circle
          key={angle}
          r="0.7"
          cx="0"
          cy="-4"
          transform={`rotate(${angle + 36})`}
          fill={SakuraColors.ink}
          opacity={0.85}
        />
      ))}
    </Svg>
  );
};
