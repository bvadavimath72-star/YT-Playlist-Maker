function record() {
    navigator.mediaDevices.getUserMedia({ audio: true }).then(stream => {
        const recorder = new MediaRecorder(stream);
        let chunks = [];
        recorder.ondataavailable = e => chunks.push(e.data);
        recorder.onstop = () => {
            const blob = new Blob(chunks, { type: 'audio/webm' });
            const form = new FormData();
            form.append("audio", blob);
            fetch("/recognize", { method: "POST", body: form })
                .then(() => window.location.reload());
        };
        recorder.start();
        setTimeout(() => recorder.stop(), 7000); // 7 seconds
    });
}
