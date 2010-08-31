#!/usr/bin/python
"""
    Module used to add and manage the Batch Jobs

    Public classes:
        Scheduler ; Manages the batch jobs and contains the methods for
                      * Batch Name Checker
                      * Batch Syntax Checker
                      * Batch Position Converter
"""
import subprocess                       # subprocess.Popen
import os                               # os.path.exists
import smtplib                          # smtplib.STMP
from email.mime.text import MIMEText    # MIMEText

from Modules import Config              # Config.Config
from Modules import Output              # Output.Output
from Modules import Parser              # Parser.Nomenclatureparser
from Modules import Mapper              # Mapper.Converter

import Mutalyzer                        # Mutalyzer.process

__all__ = ["Scheduler"]

def debug(f):
    """
        Decorator for functions called from within the daemon. Can be used
        to debug errors that are hidden because the daemon's stdout and
        errout filehandlers are closed.

        Usage: Place the decorator line above the function to investigate

        >>> @debug
        >>> def process(self) :
        >>>     pass    # function code
    """
    #NOTE: All debug functions & methods should be moved to a DEBUG module

    def _tempf(*args):
        """
            The decorated function is replaced by this function. Which sets up
            the filehandle to write to and print out additional debug info.

            The original function is called from within a try, except clause
            which catches [AND DOES NOT RERAISE] an exception occuring in the
            debugged function.

            This can result in odd behaviour, therefor the decorators should
            be removed from any production version.
        """

        of = open("/tmp/daemon.out", "a+")
        try:
            of.write("\nFunction %s\n\targs: %s\n\t" % (`f`, `args`))
            ret = f(*args)  # Actual function call
            of.write("Returns: %s" % `ret`)
            return ret
        #try
        except Exception, e:
            import traceback
            of.write("\nEXCEPTION:\n")
            traceback.print_exc(file=of)
        #except
    return _tempf
#debug


class Scheduler() :
    """
    Manages the batch jobs and contains the methods for
        Batch Name Checker
        Batch Syntax Checker
        Batch Position Converter

        Special methods:
            __init__(config, database) ;

        Public methods:
            addJob(outputFilter, eMail, queue, fromHost, jobType, Arg1)
                        ; Add a job to the database jobqueue and start the
                            batchChecker daemon.
            process()   ; Iterate over & process the jobs in the jobqueue
    """

    def __init__(self, config, database) :
        #TODO: documentation
        """
            Initialize the Scheduler, which requires a config object
            and a database connection.

            Arguments:
                config   ;
                database ;
        """

        self.__config = config
        self.__database = database
    #__init__

    def __sendMail(self, mailTo, url) :
        """
            Send an e-mail containing an url to a batch job submitter.

            Arguments:
                mailTo ; The batch job submitter.
                url    ; The url containing the results.

            Private variables:
                __config ; The variables mailMessage, mailSubject and mailFrom
                           are used.
        """

        #TODO: Handle Connection errors in a try, except clause
        #Expected errors: socket.error

        handle = open(self.__config.mailMessage)
        message = MIMEText(handle.read() % url)
        handle.close()

        message["Subject"] = self.__config.mailSubject
        message["From"] = self.__config.mailFrom
        message["To"] = mailTo

        smtpInstance = smtplib.SMTP()
        smtpInstance.connect()
        smtpInstance.sendmail(self.__config.mailFrom, mailTo,
                              message.as_string())
        smtpInstance.quit()
    #__sendMail

    def __processFlags(self, O, flags):
        """
            Translate the flags to error & info messages.

            Arguments:
                O       ; Output object of the current batchentry
                flags   ; Flags of the current batchentry

            Returns:
                skip    ; True if the entry must be skipped

            Side-effect:
                Added messages to the Output object
        """
        if not flags: return
        if 'S' in flags: #This entry is going to be skipped
            #Add a usefull message to the Output object
            if "S0" in flags:
                message = "Entry could not be formatted correctly, check "\
                        "batch input file help for details"
            elif "S9" in flags:
                message = "Empty Line"
            else:
                message = "Skipping entry"
            O.addMessage(__file__, 4, "EBSKIP", message)
            return True #skip
        #if
        if 'A' in flags: #This entry is altered before execution
            O.addMessage(__file__, 3, "WEALTER", "Entry altered before "
                    "execution")
    #__processFlags

    def __alterBatchEntries(self, jobID, old, new, flag, nselector):
        """
            Alias for the database.updateBatchDb method.

            Replace within one JobID all entries matching old with new, if
            they do not match the negative selector.

            Example:
            NM_002001(FCER1A_v001):c.1A>C ; this would result in the
                                            continuous fetching of the
                                            reference because no version
                                            number is given.
            In this case the arguments would be:
                old         ;   NM_002001
                new         ;   NM_002001.2
                nselector   ;   NM_002001[[.period.]]

            The nselector is used to prevent the replacement of
            false positives. e.g. NM_002001.1(FCER1A_v001):c.1A>C should not
            be replaced. The double bracket notation is the MySQL escape char
            for a regular expression.
        """
        self.__database.updateBatchDb(jobID, old, new, flag, nselector)
    #__alterBatchEntries

    def __skipBatchEntries(self, jobID, flag, selector):
        """
            Alias for the database.skipBatchDb method.

            Skip all batch entries that match a certain selector.
        """
        self.__database.skipBatchDb(jobID, selector, flag)
    #__skipBatchEntries

    def _updateDbFlags(self, O, jobID):
        """
            Check and set the flags for other entries of jobID.

            After each entry is ran, the Output object can contain BatchFlags.
            If these are set, this means that identical entries need to be
            skipped / altered.

            Arguments:
                O       ; Output object of the current batchentry
                jobID   ; ID of job, so that the altering is only done within
                            one job.

            Side-effect:
                Added flags to entries in the database
        """

        flags = O.getOutput("BatchFlags")
        # NOTE:
        # Flags is a list of tuples. Each tuple consists of a flag and its
        # arguments. A skipped entry has only one argument, the selector
        # E.g. ("S1", "NM_002001.$")
        # An altered entry has three arguments,
        #               old,           new          negative selector
        # E.g.("A2",("NM_002001", "NM_002001.2", "NM_002001[[.period.]]"))

        # Flags are set when an entry could be sped up. This is either the
        # case for the Retriever as for the Mutalyzer module

        if not flags: return
        #First check if we need to skip
        for flag, args in flags:
            if 'S' in flag:
                selector = args     # Strip argument
                O.addMessage(__file__, 3, "WBSKIP",
                        "All further occurrences with '%s' will be "
                        "skipped" % selector)
                self.__skipBatchEntries(jobID, flag, selector)
                return
            #if
        #for
        #If not skipflags, check if we need to alter
        for flag, args in flags:
            if 'A' in flag:
                old, new, nselector = args  #Strip arguments
                O.addMessage(__file__, 3, "WBSUBST",
                        "All further occurrences of %s will be substituted "
                        "by %s" % (old, new))
                self.__alterBatchEntries(jobID, old, new, flag, nselector)
            #if
        #for
    #_updateDbFlags

    def process(self) :
        """
            Start the mutalyzer Batch Processing. This method retrieves
            all jobs from the database and processes them in a roundrobin
            fashion. If all jobs are done the process checks if new jobs are
            added during the last processing round.

            This method uses two database tables, BatchJob and BatchQueue.

            The jobList is an array of tuples with three elements
                jobID       ;   The ID of the job
                jobType     ;   The type of the job
                argument1   ;   Currently only used for the ConversionChecker
                                to send the build version.

            If the jobList is not empty, the method will iterate once over the
            list and fetch the first entry of a job from the database table
            BatchQueue. This request returns both the input for the batch and
            the flags for the job.

            #Flags
            A job can be flagged in two ways:
                A       ;   Altered - this means that the input is altered
                            before execution. This could be the case if an
                            entry uses an accession number without a version.
                            If a version is retrieved from the NCBI, all
                            further occurences of that accession will be
                            replaced by the accession with version number.
                S       ;   Skipped - this means that this batchentry will be
                            skipped by the batchprocess. This could be the
                            case if the user made a mistake that could not be
                            auto fixed and henceforth all occurences of the
                            mistake will be skipped.
            A Flag consists of either an A or S followed by a digit, which
            refers to the reason of alteration / skip.
        """
        jobList = self.__database.getJobs()

        while jobList :
            for i, jobType, arg1 in jobList :
                inputl, flags = self.__database.getFromQueue(i)
                if not(inputl is None):
                    if jobType == "NameChecker":
                        self._processNameBatch(inputl, i, flags)
                    elif jobType == "SyntaxChecker":
                        self._processSyntaxCheck(inputl, i, flags)
                    elif jobType == "PositionConverter":
                        self._processConversion(inputl, i, arg1, flags)
                    else: #unknown jobType
                        pass #TODO: Scream burning water and remove from Queue
                else :
                    eMail, stuff, fromHost = self.__database.removeJob(i)
                    print "Job %s finished, email %s file %s" % (i, eMail, i)
                    self.__sendMail(eMail, "%sResults_%s.txt" % (fromHost, i))
                #else
            #for
            jobList = self.__database.getJobs()
        #while
    #process

    def _processNameBatch(self, cmd, i, flags):
        """
            Process an entry from the Name Batch, write the results
            to the job-file. If an Exception is raised, catch and continue.

            Arguments:
                cmd     ; The NameChecker input
                i       ; The JobID
                flags   ; Flags of the current entry

            Side-effect:
                Output written to outputfile
        """

        C = Config.Config()
        O = Output.Output(__file__, C.Output)
        O.addMessage(__file__, -1, "INFO",
            "Received NameChecker batchvariant " + cmd)

        #Read out the flags
        skip = self.__processFlags(O, flags)

        if not skip:
            #Run mutalyzer and get values from Output Object 'O'
            try:
                Mutalyzer.process(cmd, C, O)
            except Exception, e:
                #Catch all exceptions related to the processing of cmd
                O.addMessage(__file__, 4, "EBATCHU",
                        "Unexpected error occurred, dev-team notified")
                import traceback
                O.addMessage(__file__, 4, "DEBUG", `traceback.format_exc()`)
            #except
            finally:
                #check if we need to update the database
                self._updateDbFlags(O, i)
        #if

        batchOutput = O.getOutput("batchDone")

        outputline =  "%s\t" % cmd
        outputline += "%s\t" % "|".join(O.getBatchMessages(3))

        if batchOutput:
            outputline += batchOutput[0]

        outputline += "\n"

        #Output
        filename = "%s/Results_%s.txt" % (self.__config.resultsDir, i)
        if not os.path.exists(filename):
            # If the file does not yet exist, create it with the correct
            # header above it. The header is read from the config file as
            # a list. We need a tab delimited string.
            header = self.__config.nameCheckOutHeader
            handle = open(filename, 'a')
            handle.write("%s\n" % "\t".join(header))
        #if
        else:
            handle = open(filename, 'a')

        handle.write(outputline)
        handle.close()
        O.addMessage(__file__, -1, "INFO",
            "Finished NameChecker batchvariant " + cmd)
    #_processNameBatch

    def _processSyntaxCheck(self, cmd, i, flags):
        """
            Process an entry from the Syntax Check, write the results
            to the job-file.

            Arguments:
                cmd     ; The Syntax Checker input
                i       ; The JobID
                flags   ; Flags of the current entry

            Side-effect:
                Output written to outputfile
        """

        C = Config.Config()
        O = Output.Output(__file__, C.Output)
        P = Parser.Nomenclatureparser(O)

        O.addMessage(__file__, -1, "INFO",
            "Received SyntaxChecker batchvariant " + cmd)

        skip = self.__processFlags(O, flags)
        #Process
        if not skip:
            parsetree = P.parse(cmd)
        else:
            parsetree = None

        if parsetree:
            result = "OK"
        else:
            result = "|".join(O.getBatchMessages(3))

        #Output
        filename = "%s/Results_%s.txt" % (self.__config.resultsDir, i)
        if not os.path.exists(filename):
            # If the file does not yet exist, create it with the correct
            # header above it. The header is read from the config file as
            # a list. We need a tab delimited string.
            header = self.__config.syntaxCheckOutHeader
            handle = open(filename, 'a')
            handle.write("%s\n" % "\t".join(header))
        #if
        else:
            handle = open(filename, 'a')

        handle.write("%s\t%s\n" % (cmd, result))
        handle.close()
        O.addMessage(__file__, -1, "INFO",
            "Finished SyntaxChecker batchvariant " + cmd)
    #_processSyntaxCheck

    def _processConversion(self, cmd, i, build, flags):
        """
            Process an entry from the Position Converter, write the results
            to the job-file. The Position Coverter is wrapped in a try except
            block which ensures that he Batch Process keeps running. Errors
            are caught and the user will be notified.

            Arguments:
                cmd     ; The Syntax Checker input
                i       ; The JobID
                build   ; The build to use for the converter
                flags   ; Flags of the current entry

            Side-effect:
                Output written to outputfile
        """

        C = Config.Config()
        O = Output.Output(__file__, C.Output)
        variant = cmd
        variants = None
        gName = ""
        cNames = [""]

        O.addMessage(__file__, -1, "INFO",
            "Received PositionCoverter batchvariant " + cmd)

        skip = self.__processFlags(O, flags)
        if not skip:
            try:
                #process
                converter = Mapper.Converter(build, C, O)

                #Also accept chr accNo
                variant = converter.correctChrVariant(variant)

                #TODO: Parse the variant and check for c or g. This is ugly
                if not(":c." in variant or ":g." in variant):
                    #Bad name
                    P = Parser.Nomenclatureparser(O)
                    parsetree = P.parse(variant)
                #if

                if ":c." in variant:
                    # Do the c2chrom dance
                    variant = converter.c2chrom(variant)
                    # NOTE:
                    # If we received a coding reference convert that to the
                    # genomic position variant. Use that variant as the input
                    # of the chrom2c.

                # If the input is a genomic variant or if we converted a
                # coding variant to a genomic variant we try to find all
                # other affected coding variants.
                if variant and ":g." in variant:
                    # Do the chrom2c dance
                    variants = converter.chrom2c(variant)
                    if variants:
                        gName = variant
                        # Due to the cyclic behavior of the Position Converter
                        # we know for a fact that if a correct chrom name is
                        # generated by the converter.c2chrom that we will at
                        # least find one variant with chrom2c. Collect the
                        # variants from a nested lists and store them.
                        cNames = [cName for cName2 in variants.values() \
                                for cName in cName2]
            except Exception, e:
                #Catch all exceptions related to the processing of cmd
                O.addMessage(__file__, 4, "EBATCHU",
                        "Unexpected error occurred, dev-team notified")
            #except
        #if

        error = "%s" % "|".join(O.getBatchMessages(3))

        #Output
        filename = "%s/Results_%s.txt" % (self.__config.resultsDir, i)
        if not os.path.exists(filename):
            # If the file does not yet exist, create it with the correct
            # header above it. The header is read from the config file as
            # a list. We need a tab delimited string.
            header = self.__config.positionConverterOutHeader
            handle = open(filename, 'a')
            handle.write("%s\n" % "\t".join(header))
        #if
        else:
            handle = open(filename, 'a')

        handle.write("%s\t%s\t%s\t%s\n" % (cmd, error, gName, "\t".join(cNames)))
        handle.close()
        O.addMessage(__file__, -1, "INFO",
            "Finisehd PositionCoverter batchvariant " + cmd)
    #_processConversion



    def addJob(self, outputFilter, eMail, queue, fromHost, jobType, Arg1) :
        """
            Add a job to the Database and start the BatchChecker.

            Arguments:
                outputFilter ; Filter the output of Mutalyzer
                eMail        ; e-mail address of batch supplier
                queue        ; A list of jobs
                fromHost     ; From where is the request made
                jobType      ; The type of Batch Job that should be run
                Arg1         ; Batch Arguments, for now only build info
        """
        #TODO: outputFilter is not used

        # Add jobs to the database
        jobID = self.__database.addJob(outputFilter, eMail,
                fromHost, jobType, Arg1)

        for inputl in queue :
            # NOTE:
            # This is a very dirty way to skip entries before they are fed
            # to the batch processes. This is needed for e.g. an empty line
            # or because the File Module noticed wrong formatting. These lines
            # used to be discarded but are now preserved by the escape string.
            # The benefit of this is that the users input will match the
            # output in terms of input line and outputline.
            if inputl.startswith("~!"): #Dirty Escape
                inputl = inputl[2:]
                if inputl:
                    flag = "S0"     # Flag for wrong format
                else:
                    flag = "S9"     # Flag for empty line
                    inputl = " " #Database doesn't like an empty inputfield
            else:
                flag = None
            self.__database.addToQueue(jobID, inputl, flag)

        # Spawn child
        p = subprocess.Popen(["MutalyzerBatch",
            "src/BatchChecker.py"], executable="python")

        #Wait for the BatchChecker to fork of the Daemon
        p.communicate()
        return jobID
    #addJob
#Scheduler

if __name__ == "__main__" :
    pass
