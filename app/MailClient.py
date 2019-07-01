'''
pluggable mail client.
'''
from abc import ABCMeta, abstractmethod
import imaplib, email


class MailClient(metaclass=ABCMeta):
    '''
    all mail clients require the below methods
    '''

    def __init__(self, server, email, passwd, port=993):
        self.server = server
        self.email = email
        self.passwd = passwd
        self.port = port

    @abstractmethod
    def verify_mailboxes():
        '''
        this method should verify that the "processed" and "failures"
        mailboxes exist. If they don't, they should be created.
        '''
        pass

    @abstractmethod
    def open_session():
        '''
        opens an imap session with the mail server
        '''
        pass

    @abstractmethod
    def close_session():
        '''
        closes an imap session with the mail server
        '''
        pass

    @abstractmethod
    def mark_processed():
        '''
        this is sent a message id that should be marked as read
        so that it's not attempted to be processed on future connections.
        it should also be moved into the "processed" folder.
        '''
        pass

    @abstractmethod
    def mark_failed():
        '''
        this is sent a message id that should be marked as unread
        so that it's attempted to be processed on future connections.
        it should also be moved to the "failures" folder.
        '''
        pass


class Gmail(MailClient):
    def __init__(self, server, email, passwd, port=993):
        super().__init__(server, email, passwd, port)
        self.session = None

    def __enter__(self):
        self.open_session()
        return self

    def __exit__(self, ex_type, ex_value, traceback):
        self.close_session()

    def verify_mailboxes(self):
        if not self.session:
            self.open_session()
        resps = []
        boxes = self.session.list()
        processed_box_exists = [box.split()[-1] == b'"processed"' for box in boxes[1]]
        if not any(processed_box_exists):
            typ, create_resp = self.session.create('processed')
            resps.append(create_resp)
        failures_box_exists = [box.split()[-1] == b'"failures"' for box in boxes[1]]
        if not any(failures_box_exists):
            typ, create_resp = self.session.create('failures')
            resps.append(create_resp)
        if not resps:
            return 'boxes already exists'
        else:
            return resps

    def open_session(self):
        if not self.session:
            self.session = imaplib.IMAP4_SSL(self.server)
            self.session.login(self.email, self.passwd)
            return self.session

    def close_session(self):
        if self.session:
            if self.session.state == 'SELECTED':
                self.session.close()
            if self.session.state == 'AUTH':
                self.session.logout()

    def mark_processed(self, msg_id):
        '''
        gmail uses labels instead of folders so instead of moving
        we just add the label
        '''
        if not self.session:
            self.open_session()

        self.session.store(msg_id, '+X-GM-LABELS', 'processed')
        self.session.store(msg_id, '+FLAGS', '\\Seen')

        # if message was previously a failure, remove the tag
        self.session.store(msg_id, '-X-GM-LABELS', 'failures')

    def mark_failed(self, msg_id):
        '''
        gmail uses labels instead of folders so instead of moving
        we just add the label
        '''
        # mark as unseen so we can attempt to process it later
        if not self.session:
            self.open_session()
        self.session.store(msg_id, '-FLAGS', '\\Seen')
        self.session.store(msg_id, '+X-GM-LABELS', 'failures')

    def __repr__(self):
        server = f'<Gmail server: {self.server}, '
        email = f'user: {self.email}, '
        port = f'port: {self.port}>'
        rep = server + email + port
        return rep
