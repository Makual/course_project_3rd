'use client'
import {Badge} from "@/shared/ui/badge"
import {Button} from "@/shared/ui/button"
import {Card, CardContent} from "@/shared/ui/card"
import {CtgCombinedPanel} from "@/features/ctg/ui/ctg-combined-panel"
import {generateCtgData} from "@/features/ctg/lib/mock"
import {Copy, HeartPulse} from "lucide-react"
import Link from "next/link"
import Image from "next/image";
import {Label} from "@/shared/ui/label";
import {Textarea} from "@/shared/ui/textarea";
import * as React from "react";
import {
    useGetMonitorReportApiMonitorsMonitorIdReportGet
} from "@/entities/generated/endpoints/ктг-мониторинг-api-v10-0-1-гц";

export default function SummaryPage() {
    const top = generateCtgData(120, {topBaseline: 120, bottomBaseline: 20})
    const bottom = generateCtgData(120, {topBaseline: 45, bottomBaseline: 10})
    const start = new Date()
    const monitorId = typeof window !== 'undefined' ? (sessionStorage.getItem('ktg_monitor_id') || '') : ''

    const getReportQuery = useGetMonitorReportApiMonitorsMonitorIdReportGet(monitorId || '');

    return (
        <main className="p-4 md:p-6 lg:p-8">
            <h1 className="text-5xl font-semibold mb-4">Итог</h1>

            <div className="grid grid-cols-1 lg:grid-cols-[2fr_1fr] gap-3 mb-3">
                <Card className="border-input">
                    <CardContent className="p-4 md:p-6 space-y-2">
                        <div className="text-xl font-medium">Итог для МИС</div>
                        <div
                            className="rounded-xl bg-input/20 border border-input h-36 p-3 text-muted-foreground">Текст
                        </div>
                        <div className="flex justify-end">
                            <Button variant="outline" className="gap-2"><Copy className="size-4"/> Копировать</Button>
                        </div>
                    </CardContent>
                </Card>

                <Card className="border-input bg-destructive/10">
                    <CardContent className="p-4 md:p-6 space-y-3">
                        <Badge variant="destructive" className="h-8 gap-2"><HeartPulse className="size-4"/> Риск острой
                            гипоксии</Badge>
                        <div className="text-xl">Обратите внимание, нужно срочно оказать медицинскую помощь</div>
                    </CardContent>
                </Card>
            </div>

            <div className="mb-3">
                <div className="flex items-center justify-between mb-2">
                    <div className="text-2xl font-semibold">ЧСС</div>
                    <Badge className="h-7 bg-red-500/20 text-red-400 border-red-500/20">Высокий ЧСС</Badge>
                </div>
                <CtgCombinedPanel disableDopInfo data={top} lineKey="heart_beat" color="#22c55e" startTime={start}
                                  sampleMs={60_000} yDomain={[80, 200]}/>
            </div>

            <div className="mb-3">
                <div className="flex items-center justify-between mb-2">
                    <div className="text-2xl font-semibold">Сократительная активность матки</div>
                    <Badge className="h-7 bg-red-500/20 text-red-400 border-red-500/20">Высокая частота маточных
                        сокращений</Badge>
                </div>
                <CtgCombinedPanel disableDopInfo data={bottom} lineKey="pussy_power" color="#22c55e" startTime={start}
                                  sampleMs={60_000} yDomain={[0, 100]} />
            </div>

            <div className={'mt-4 space-y-4'}>
                <Label htmlFor="message">Сформированный отчет:</Label>
                <Textarea id={'message'} className={'h-[300px]'} value={getReportQuery.data?.text_report}/>
                <div>
                    <Button variant={'outline'} className={'rounded-xl'} onClick={() => {
                        const text = getReportQuery.data?.text_report || 'Отчет недоступен'
                        const blob = new Blob([text], {type: 'text/plain;charset=utf-8'})
                        const url = URL.createObjectURL(blob)
                        const a = document.createElement('a')
                        a.href = url
                        a.download = `ctg_report_${monitorId || 'session'}.txt`
                        document.body.appendChild(a)
                        a.click()
                        a.remove()
                        URL.revokeObjectURL(url)
                    }}>Скачать отчет (.txt)</Button>
                </div>
            </div>

            <div className="sticky bottom-3 left-0 right-0 mt-4">
                <div className="mx-auto max-w-screen-2xl flex items-center gap-3 px-2">
                    <Link href="/">
                        <Button variant="outline" className="rounded-xl">На главный</Button>
                    </Link>
                    <Button variant="outline" className="rounded-xl">Скачать PDF</Button>
                    <Button variant="outline" className="rounded-xl">Распечатать итог для медкарты</Button>
                    <div className="flex-1"/>
                    <Link href="/start-process">
                        <Button variant={'bluest'} className="cursor-pointer rounded-2xl h-12 text-lg px-6">
                            <Image width={17} height={20} src={'/ArrowRight.svg'} alt={'right'}/> Начать новый приём
                        </Button>
                    </Link>
                </div>
            </div>
        </main>
    )
}


