'use client'

import { CtgPanel } from '@/features/ctg/ui/ctg-panel'
import { Badge } from '@/shared/ui/badge'
import { Button } from '@/shared/ui/button'
import { Card, CardContent } from '@/shared/ui/card'
import { Tabs, TabsContent, TabsList, TabsTrigger } from '@/shared/ui/tabs'
import { Copy, X } from 'lucide-react'
import {generateCtgData} from "@/features/ctg/lib/mock";

export function HistoryDetails({ onClose }: { onClose: () => void }) {
  const top = generateCtgData(120, { topBaseline: 125, bottomBaseline: 20 })
  const bottom = generateCtgData(120, { topBaseline: 40, bottomBaseline: 10 })

  return (
    <Card className="border-input">
      <CardContent className="p-4 md:p-6">
        <div className="flex items-start justify-between gap-3 mb-4">
          <div className="flex flex-wrap items-center gap-2 text-sm text-muted-foreground">
            <div className="text-base text-foreground font-medium">
              Роды, кабинет 4, прошли, с 19:00 24.08 по 02:00 25.08
            </div>
            <Badge className="h-7 rounded-full">36 недель</Badge>
            <div className="mx-1">•</div>
            <div>42 года</div>
            <div className="mx-1">•</div>
            <div>Гипоксия</div>
            <div className="mx-1">•</div>
            <div>Диабет</div>
          </div>
          <Button
            size="icon"
            variant="outline"
            aria-label="Close"
            className="rounded-xl"
            onClick={onClose}
          >
            <X className="size-4" />
          </Button>
        </div>

        <Tabs defaultValue="ctg">
          <TabsList>
            <TabsTrigger value="ctg">КТГ</TabsTrigger>
            <TabsTrigger value="anamnesis">Анамнез</TabsTrigger>
            <TabsTrigger value="uzi">УЗИ</TabsTrigger>
          </TabsList>
          <TabsContent value="ctg" className="mt-4 space-y-3">
            <CtgPanel
              data={top}
              lineKey="heart_beat"
              color="#22c55e"
              value={130}
              valueTitle="ЧСС • FHR1"
              areaName={'ЧСС'}
            />
            <CtgPanel
              data={bottom}
              lineKey="pussy_power"
              color="#22c55e"
              value={160}
              areaName={'Сократительная активность матки'}
              valueTitle="Сократительная активность матки • TOCO"
            />

            <div className="space-y-3">
              <Section title="Итог для МИС" />
              <Section title="Итог" />
            </div>

            <div className="flex items-center gap-2 pt-2">
              <Button variant="outline">Скачать PDF</Button>
              <Button variant="outline">Распечатать итог для медкарты</Button>
            </div>
          </TabsContent>
          <TabsContent
            value="anamnesis"
            className="text-muted-foreground text-sm"
          >
            Нет данных
          </TabsContent>
          <TabsContent value="uzi" className="text-muted-foreground text-sm">
            Нет данных
          </TabsContent>
        </Tabs>
      </CardContent>
    </Card>
  )
}

function Section({ title }: { title: string }) {
  return (
    <div className="space-y-2">
      <div className="text-sm text-muted-foreground flex items-center justify-between">
        <span>{title}</span>
        <Button variant="outline" size="sm" className="gap-2">
          <Copy className="size-4" /> Копировать
        </Button>
      </div>
      <div className="rounded-lg bg-input/20 border border-input h-28 p-3 text-muted-foreground">
        Текст
      </div>
    </div>
  )
}







