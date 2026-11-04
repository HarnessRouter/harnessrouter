// See package.json. Nothing calls this while images.unoptimized is true; if that changes, this says why it fails.
throw Object.assign(new Error('This console does not optimize images: images.unoptimized is on and sharp is not installed.'), { code: 'MODULE_NOT_FOUND' });
