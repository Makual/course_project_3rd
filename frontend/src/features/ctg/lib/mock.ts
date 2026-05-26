export type CtgPoint = {
  index: number
  heart_beat: number
  pussy_power: number
}

export type CtgStatus = 'acute' | 'chronic' | 'normal'

export type CtgTile = {
  title: string
  room: string
  status: CtgStatus
  data: CtgPoint[]
}

function clamp(value: number, min: number, max: number) {
  return Math.min(max, Math.max(min, value))
}

function randomBetween(min: number, max: number) {
  return Math.random() * (max - min) + min
}

export function generateCtgData(
  length = 90,
  {
    topBaseline = 150,
    topVariance = 8,
    bottomBaseline = 20,
    bottomVariance = 4,
  }: {
    topBaseline?: number
    topVariance?: number
    bottomBaseline?: number
    bottomVariance?: number
  } = {}
): CtgPoint[] {
  let heart_beat = topBaseline
  let pussy_power = bottomBaseline

  const data: CtgPoint[] = []
  for (let i = 0; i < length; i++) {
    // Add slow drift and small random noise
    heart_beat += randomBetween(-topVariance, topVariance)
    pussy_power += randomBetween(-bottomVariance, bottomVariance)

    // Occasional accelerations/decelerations for heart_beat
    if (Math.random() < 0.08) heart_beat += randomBetween(-25, 25)
    // Occasional contractions for pussy_power
    if (Math.random() < 0.06) pussy_power += randomBetween(10, 35)

    heart_beat = clamp(heart_beat, 90, 190)
    pussy_power = clamp(pussy_power, 0, 90)
    // Slow recovery to baseline
    heart_beat += (topBaseline - heart_beat) * 0.03
    pussy_power += (bottomBaseline - pussy_power) * 0.04

    data.push({ index: i, heart_beat: heart_beat, pussy_power: pussy_power })
  }
  return data
}

export function getStatusColors(status: CtgStatus) {
  switch (status) {
    case 'acute':
      return { heart_beat: '#ef4444', pussy_power: '#ef4444' } // red
    case 'chronic':
      return { heart_beat: '#14b8a6', pussy_power: '#f59e0b' } // teal + amber
    case 'normal':
      return { heart_beat: '#22c55e', pussy_power: '#22c55e' } // green
  }
}

export function getStatusBadge(status: CtgStatus) {
  switch (status) {
    case 'acute':
      return { label: 'Риск острой гипоксии', variant: 'destructive' as const }
    case 'chronic':
      return {
        label: 'Признаки хронической гипоксии',
        variant: 'secondary' as const,
      }
    case 'normal':
      return { label: 'Норма', variant: 'default' as const }
  }
}

export function createDemoTiles(): CtgTile[] {
  return [
    {
      title: 'Роды',
      room: 'Кабинет 7',
      status: 'acute',
      data: generateCtgData(120, { topBaseline: 150, bottomBaseline: 25 }),
    },
    {
      title: 'Роды',
      room: 'Кабинет 7',
      status: 'chronic',
      data: generateCtgData(120, { topBaseline: 145, bottomBaseline: 35 }),
    },
    {
      title: 'Роды',
      room: 'Кабинет 7',
      status: 'chronic',
      data: generateCtgData(120, { topBaseline: 160, bottomBaseline: 20 }),
    },
    {
      title: 'Роды',
      room: 'Кабинет 7',
      status: 'normal',
      data: generateCtgData(120, { topBaseline: 150, bottomBaseline: 35 }),
    },
  ]
}


