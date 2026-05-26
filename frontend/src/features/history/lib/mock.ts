export type Gender = 'male' | 'female'

export type HistoryItem = {
  id: string
  date: string // DD.MM
  time: string // HH:MM - HH:MM
  gender: Gender
  score: string // e.g. 4,13
  firstName: string
  lastName: string
  doctor: string
  medsister?: string
}

const FIRST_NAMES = ['Надежда', 'Анна', 'Екатерина', 'Ольга', 'Мария']
const LAST_NAMES = ['Иванова', 'Петрова', 'Сидорова', 'Кузнецова', 'Миронова']
const DOCTORS = [
  'Александр Стихин',
  'Ирина Смирнова',
  'Павел Кузнецов',
  'Антон Волков',
]

function pick<T>(arr: T[]): T {
  return arr[Math.floor(Math.random() * arr.length)]
}

export function generateHistoryList(count = 9): HistoryItem[] {
  const items: HistoryItem[] = []
  for (let i = 0; i < count; i++) {
    const date = String(3 + (i % 3)).padStart(2, '0') + '.08'
    const start = 18 + (i % 2)
    const time = `${String(start).padStart(2, '0')}:30 - ${String(start + 1).padStart(2, '0')}:30`
    const gender: Gender = Math.random() > 0.5 ? 'male' : 'female'
    const score = `${(3.9 + Math.random() * 0.5).toFixed(2).replace('.', ',')}`
    items.push({
      id: `${i}`,
      date,
      time,
      gender,
      score,
      firstName: pick(FIRST_NAMES),
      lastName: pick(LAST_NAMES),
      doctor: pick(DOCTORS),
    })
  }
  return items
}







