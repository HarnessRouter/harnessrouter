/* Hand a native program its prompt from a file instead of from the command line, for a CLI that takes its
 * prompt only as an argument and reads it from nowhere else: jcode, whose `run` takes only <MESSAGE>
 * (runner/server.py, _build_jcode). Built into the image beside the runner (Dockerfile, stage "prompt-argv").
 *
 *     LD_PRELOAD=<this library> HR_PROMPT_FILE=<prompt file> HR_PROMPT_EXE=<the program's own path> \
 *         <program> ... -- {hr:prompt}
 *
 * The dynamic loader runs this library's initializer before the program's own, with the program's argc and argv.
 * In the program named by HR_PROMPT_EXE (matched against /proc/self/exe, so a shell or launcher in between, which
 * holds the same arguments, never takes the text into an exec of its own), the argument equal to PROMPT_ARG is
 * pointed at the file's text. The program then reads the prompt from its arguments as it would have from its
 * command line, while the command line it was started with (what `ps` lists, /proc/<pid>/cmdline, which is the
 * memory the kernel laid out at exec and is not touched here) holds only the placeholder. The file is the
 * session's own, 0600 (server.py, _prompt_handover), and goes as soon as it is read.
 *
 * The program's own environment loses all three variables here, so nothing it starts loads this library or
 * looks for the prompt. Anything that stops the hand-over in the program stops the program, loudly: a turn never
 * runs with the placeholder as its prompt. Everywhere else this does nothing at all.
 *
 * libc only. This file ships with the runner; the library is root-owned and read-only, never in a session's tree.
 */
#define _GNU_SOURCE
#include <errno.h>
#include <fcntl.h>
#include <stdlib.h>
#include <string.h>
#include <sys/stat.h>
#include <unistd.h>

#define PROMPT_ARG "{hr:prompt}"

static void say_and_exit(const char *why) {
    static const char head[] = "the prompt could not be handed over: ";
    ssize_t ignored = write(2, head, sizeof head - 1);
    ignored = write(2, why, strlen(why));
    ignored = write(2, "\n", 1);
    (void)ignored;
    _exit(2);
}

static void hand_over(int argc, char **argv, char **envp) {
    (void)envp;
    const char *file = getenv("HR_PROMPT_FILE");
    const char *exe = getenv("HR_PROMPT_EXE");
    if (file == NULL || exe == NULL)
        return;
    char self[4096];
    ssize_t n = readlink("/proc/self/exe", self, sizeof self - 1);
    if (n <= 0)
        return;
    self[n] = '\0';
    if (strcmp(self, exe) != 0)
        return;                               /* a launcher in between: it passes the placeholder on as it is */
    char path[4096];
    if (strlen(file) >= sizeof path)
        say_and_exit("its path is too long");
    strcpy(path, file);
    unsetenv("HR_PROMPT_FILE");
    unsetenv("HR_PROMPT_EXE");
    unsetenv("LD_PRELOAD");
    int at = -1;
    for (int i = 1; i < argc; i++) {
        if (strcmp(argv[i], PROMPT_ARG) == 0) {
            at = i;
            break;
        }
    }
    if (at < 0)
        say_and_exit("the command line holds no place for it");
    int fd = open(path, O_RDONLY | O_CLOEXEC | O_NOFOLLOW);
    if (fd < 0)
        say_and_exit(strerror(errno));
    struct stat st;
    if (fstat(fd, &st) != 0 || !S_ISREG(st.st_mode))
        say_and_exit("it is not a file");
    char *text = malloc((size_t)st.st_size + 1);
    if (text == NULL)
        say_and_exit("out of memory");
    size_t got = 0;
    while (got < (size_t)st.st_size) {
        ssize_t r = read(fd, text + got, (size_t)st.st_size - got);
        if (r < 0 && errno == EINTR)
            continue;
        if (r <= 0)
            say_and_exit("it was cut short");
        got += (size_t)r;
    }
    text[got] = '\0';
    close(fd);
    unlink(path);                             /* the runner removes it when the turn ends in any case */
    argv[at] = text;                          /* kept for the life of the process, as an argument is */
}

/* .init_array, not a plain constructor: glibc hands these the program's argc, argv and envp. */
__attribute__((used, section(".init_array"))) static void (*hr_prompt_argv)(int, char **, char **) = hand_over;
