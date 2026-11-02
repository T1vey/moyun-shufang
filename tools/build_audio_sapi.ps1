param([Parameter(Mandatory=$true)][string]$TextDirectory,
      [Parameter(Mandatory=$true)][string]$OutputDirectory,
      [string]$Voice='Microsoft Huihui Desktop')
$ErrorActionPreference='Stop'
Add-Type -AssemblyName System.Speech
$synth=New-Object System.Speech.Synthesis.SpeechSynthesizer
try {
    $synth.SelectVoice($Voice)
    $synth.Rate=-1
    $synth.Volume=100
    $format=New-Object System.Speech.AudioFormat.SpeechAudioFormatInfo(48000,
        [System.Speech.AudioFormat.AudioBitsPerSample]::Sixteen,
        [System.Speech.AudioFormat.AudioChannel]::Mono)
    foreach($file in (Get-ChildItem -LiteralPath $TextDirectory -Filter '*.json' | Sort-Object Name)) {
        $item=Get-Content -LiteralPath $file.FullName -Raw -Encoding UTF8 | ConvertFrom-Json
        if($item.id -notmatch '^(poem|masterpiece)_[a-z0-9]+$'){throw 'Invalid audio identifier'}
        $target=Join-Path $OutputDirectory $item.id
        New-Item -ItemType Directory -Force $target | Out-Null
        $index=0
        foreach($sentence in $item.sentences) {
            $wav=Join-Path $target ('{0:D4}.wav' -f $index)
            $synth.SetOutputToWaveFile($wav,$format)
            $synth.Speak([string]$sentence)
            $synth.SetOutputToNull()
            $index++
        }
        Write-Output ('SAPI_READY '+$item.id+' '+$index)
    }
} finally {$synth.Dispose()}
