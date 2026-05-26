'use client'

import { UploadModal } from '@/features/upload/ui/upload-modal'
import { Button } from '@/shared/ui/button'
import { Input } from '@/shared/ui/input'
import { ChevronDown, Download, Settings } from 'lucide-react'
import * as React from 'react'

export function HistoryToolbar() {
  const [uploadOpen, setUploadOpen] = React.useState(false)
  return (
    <div className="flex items-center justify-between gap-3 mb-4">
      <div className="flex items-center gap-2 text-sm text-muted-foreground">
        <span>Масштаб</span>
        <Button variant="outline" className="gap-1">
          20 мин <ChevronDown className="size-4" />
        </Button>
      </div>
      <div className="flex items-center gap-2">
        <Button
          variant="outline"
          className="gap-2"
          onClick={() => setUploadOpen(true)}
        >
          <Download className="size-4" /> Загрузить данные
        </Button>
        <Button variant="outline" size="icon" aria-label="Settings">
          <Settings className="size-4" />
        </Button>
        <div className="text-sm text-muted-foreground">14:30</div>
      </div>
      <UploadModal open={uploadOpen} onOpenChange={setUploadOpen} />
    </div>
  )
}
